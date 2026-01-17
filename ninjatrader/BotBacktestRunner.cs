#region Using declarations
using System;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Globalization;
using System.Text;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class BotBacktestRunner : Strategy
    {
        public enum SessionMode
        {
            RTH = 0,
            ETH = 1,
            BOTH = 2
        }

        private enum SetupAction
        {
            NONE = 0,
            BUY = 1,
            SELL = 2
        }

        private sealed class SetupResult
        {
            public SetupAction Action { get; set; } = SetupAction.NONE;
            public double Confidence { get; set; } = 0.0; // 0..1
            public string Reason { get; set; } = "";
        }

        #region Optimizable Parameters (Swarm v1)
        [NinjaScriptProperty]
        [Range(1, 200)]
        [Display(Name = "Qty", Order = 1, GroupName = "Swarm")]
        public int Qty { get; set; }

        [NinjaScriptProperty]
        [Range(0, 500)]
        [Display(Name = "StopLossTicks", Order = 2, GroupName = "Swarm")]
        public int StopLossTicks { get; set; }

        [NinjaScriptProperty]
        [Range(0, 500)]
        [Display(Name = "TakeProfitTicks", Order = 3, GroupName = "Swarm")]
        public int TakeProfitTicks { get; set; }

        [NinjaScriptProperty]
        [Range(0, 500)]
        [Display(Name = "MinAtrTicks", Order = 4, GroupName = "Swarm")]
        public int MinAtrTicks { get; set; }

        [NinjaScriptProperty]
        [Range(0, 500)]
        [Display(Name = "CooldownBars", Order = 5, GroupName = "Swarm")]
        public int CooldownBars { get; set; }

        [NinjaScriptProperty]
        [Range(0, 1000)]
        [Display(Name = "MaxTradesPerSession", Order = 6, GroupName = "Swarm")]
        public int MaxTradesPerSession { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "SessionMode", Order = 7, GroupName = "Swarm")]
        public SessionMode Session { get; set; }

        [NinjaScriptProperty]
        [Range(0.0, 1.0)]
        [Display(Name = "MinConfidence", Order = 8, GroupName = "Swarm")]
        public double MinConfidence { get; set; }

        [NinjaScriptProperty]
        [Range(0.0, 100000.0)]
        [Display(Name = "MaxLossUsd", Order = 9, GroupName = "Swarm")]
        public double MaxLossUsd { get; set; }

        [NinjaScriptProperty]
        [Range(0, 2359)]
        [Display(Name = "StartTimeHHmm", Order = 10, GroupName = "Swarm")]
        public int StartTimeHHmm { get; set; }

        [NinjaScriptProperty]
        [Range(0, 2359)]
        [Display(Name = "EndTimeHHmm", Order = 11, GroupName = "Swarm")]
        public int EndTimeHHmm { get; set; }

        // Setup params (cheap, deterministic)
        [NinjaScriptProperty]
        [Range(10, 300)]
        [Display(Name = "EmaTrendLen", Order = 20, GroupName = "Setup")]
        public int EmaTrendLen { get; set; }

        [NinjaScriptProperty]
        [Range(5, 200)]
        [Display(Name = "EmaPullbackLen", Order = 21, GroupName = "Setup")]
        public int EmaPullbackLen { get; set; }

        [NinjaScriptProperty]
        [Range(2, 50)]
        [Display(Name = "BosLookback", Order = 22, GroupName = "Setup")]
        public int BosLookback { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "EnableLogging", Order = 99, GroupName = "Debug")]
        public bool EnableLogging { get; set; }
        #endregion

        // Hard rule: Swarm v1 runs ONLY in Strategy Analyzer Optimization (deterministic, no network).
        private string _runId;
        private bool _tradingEnabled = true;
        private string _disabledReason = "";
        private int _cooldownLeft = 0;
        private int _tradesThisSession = 0;

        // ATR(14) Wilder (no indicator object)
        private const int ATR_N = 14;
        private double _atr = 0.0;
        private int _atrWarm = 0;
        private double _prevClose = 0.0;
        private bool _hasPrev = false;

        // Equity curve tracking
        private double _equityHigh = 0.0;
        private double _maxDrawdown = 0.0;

        // Counters
        private long _signalsSeen = 0;
        private long _tradesTaken = 0;
        private long _skippedConfidence = 0;
        private long _skippedAtr = 0;
        private long _skippedCooldown = 0;
        private long _skippedSession = 0;
        private long _skippedMaxTrades = 0;
        private long _skippedHardStop = 0;

        // Profesor logging throttle
        private string _lastWaitReason = "";
        private int _lastExplainBar = -999999;
        private const int EXPLAIN_EVERY_N_BARS = 50;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "BotBacktestRunner";
                Description = "Swarm v1: Strategy Analyzer Optimization only, 1 decision per closed bar, no network/WS/DB.";
                Calculate = Calculate.OnBarClose; // OBLIGATORIO
                BarsRequiredToTrade = 250;

                Qty = 1;
                StopLossTicks = 10;
                TakeProfitTicks = 12;
                MinAtrTicks = 6;
                CooldownBars = 2;
                MaxTradesPerSession = 20;
                Session = SessionMode.RTH;
                MinConfidence = 0.10;
                MaxLossUsd = 1200.0;
                StartTimeHHmm = 930;
                EndTimeHHmm = 1600;

                EmaTrendLen = 200;
                EmaPullbackLen = 20;
                BosLookback = 10;

                EnableLogging = true;
            }
            else if (State == State.DataLoaded)
            {
                _runId = "swarm_" + Guid.NewGuid().ToString("N");
                ResetSession();
                if (EnableLogging) Print("Swarm v1 loaded runId=" + _runId);
            }
            else if (State == State.Terminated)
            {
                EmitSummary();
            }
        }

        private void ResetSession()
        {
            _tradesThisSession = 0;
            _cooldownLeft = 0;
        }

        protected override void OnBarUpdate()
        {
            if (!IsInStrategyAnalyzer)
                return;

            UpdateAtr();
            if (CurrentBar < BarsRequiredToTrade)
                return;

            bool isFirstSessionBar = false;
            try { isFirstSessionBar = Bars.IsFirstBarOfSession; } catch { isFirstSessionBar = false; }
            if (isFirstSessionBar) ResetSession();

            if (_cooldownLeft > 0) _cooldownLeft--;

            ApplyHardStopIfNeeded();
            if (!_tradingEnabled)
            {
                _skippedHardStop++;
                ExplainWait("hard_stop:" + _disabledReason);
                return;
            }

            if (!IsInAllowedSessionWindow())
            {
                _skippedSession++;
                ExplainWait("session_filter");
                return;
            }

            if (MaxTradesPerSession > 0 && _tradesThisSession >= MaxTradesPerSession)
            {
                _skippedMaxTrades++;
                ExplainWait("max_trades_session");
                return;
            }

            if (_cooldownLeft > 0)
            {
                _skippedCooldown++;
                ExplainWait("cooldown");
                return;
            }

            // ATR gate
            double tickSize = GetTickSize();
            double atrTicks = tickSize > 0 ? (_atr / tickSize) : 0.0;
            if (_atrWarm < ATR_N || atrTicks < Math.Max(0, MinAtrTicks))
            {
                _skippedAtr++;
                ExplainWait("atr_gate atrTicks=" + atrTicks.ToString("0.0", CultureInfo.InvariantCulture));
                return;
            }

            var setup = EvaluateSetup(tickSize);
            if (setup.Action == SetupAction.NONE)
            {
                ExplainWait(setup.Reason);
                return;
            }

            _signalsSeen++;

            double minC = Clamp01(MinConfidence);
            if (setup.Confidence < minC)
            {
                _skippedConfidence++;
                ExplainWait("low_conf " + setup.Reason + " conf=" + setup.Confidence.ToString("0.00", CultureInfo.InvariantCulture));
                return;
            }

            ExecuteSetup(setup);
        }

        private double GetTickSize()
        {
            try
            {
                if (Instrument != null && Instrument.MasterInstrument != null && Instrument.MasterInstrument.TickSize > 0)
                    return Instrument.MasterInstrument.TickSize;
            }
            catch { }
            return 0.25;
        }

        private void UpdateAtr()
        {
            double high = High[0];
            double low = Low[0];
            double close = Close[0];

            double tr;
            if (!_hasPrev)
            {
                tr = high - low;
            }
            else
            {
                tr = Math.Max(high - low, Math.Max(Math.Abs(high - _prevClose), Math.Abs(low - _prevClose)));
            }
            _prevClose = close;
            _hasPrev = true;

            if (_atrWarm < ATR_N)
            {
                _atr = ((_atr * _atrWarm) + tr) / (_atrWarm + 1);
                _atrWarm++;
                return;
            }

            _atr = ((_atr * (ATR_N - 1)) + tr) / ATR_N;
        }

        private bool IsInAllowedSessionWindow()
        {
            if (Session == SessionMode.BOTH)
                return true;

            int hhmm = 0;
            try { hhmm = (Time[0].Hour * 100) + Time[0].Minute; } catch { hhmm = 0; }

            int start = Math.Max(0, Math.Min(2359, StartTimeHHmm));
            int end = Math.Max(0, Math.Min(2359, EndTimeHHmm));

            bool inRth = true;
            if (start != 0 || end != 0)
            {
                if (start <= end)
                    inRth = (hhmm >= start && hhmm <= end);
                else
                    inRth = (hhmm >= start || hhmm <= end); // overnight
            }

            if (Session == SessionMode.RTH) return inRth;
            return !inRth;
        }

        private void ApplyHardStopIfNeeded()
        {
            double realized = 0.0;
            try { realized = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit; } catch { realized = 0.0; }

            if (realized > _equityHigh) _equityHigh = realized;
            double dd = _equityHigh - realized;
            if (dd > _maxDrawdown) _maxDrawdown = dd;

            if (MaxLossUsd > 0.0 && realized <= -Math.Abs(MaxLossUsd))
            {
                _tradingEnabled = false;
                _disabledReason = "max_loss realized=" + realized.ToString("0.00", CultureInfo.InvariantCulture);
            }
        }

        private SetupResult EvaluateSetup(double tickSize)
        {
            // Minimal, audit-able setup:
            // Trend: EMA(trend) slope + price above/below.
            // Pullback: wick touches EMA(pullback) and closes back.
            // Confirm: BOS (break of previous high/low over lookback).
            int tLen = Math.Max(10, EmaTrendLen);
            int pLen = Math.Max(5, EmaPullbackLen);
            int lb = Math.Max(2, BosLookback);

            double emaT0 = EMA(tLen)[0];
            double emaT1 = EMA(tLen)[1];
            double emaP0 = EMA(pLen)[0];

            double c0 = Close[0];
            double o0 = Open[0];
            double h0 = High[0];
            double l0 = Low[0];

            bool trendUp = c0 > emaT0 && emaT0 >= emaT1;
            bool trendDown = c0 < emaT0 && emaT0 <= emaT1;

            bool pullLong = l0 <= emaP0 && c0 >= emaP0;
            bool pullShort = h0 >= emaP0 && c0 <= emaP0;

            double hh = High[1];
            double ll = Low[1];
            for (int i = 2; i <= lb; i++)
            {
                if (High[i] > hh) hh = High[i];
                if (Low[i] < ll) ll = Low[i];
            }

            bool bosUp = c0 > hh;
            bool bosDown = c0 < ll;

            // Confidence (cheap): based on BOS + candle direction + trend distance normalized by ATR
            double atrTicks = tickSize > 0 ? (_atr / tickSize) : 0.0;
            double distTrendTicks = tickSize > 0 ? (Math.Abs(c0 - emaT0) / tickSize) : 0.0;
            double distScore = (atrTicks > 0) ? Math.Min(1.0, distTrendTicks / Math.Max(1.0, atrTicks)) : 0.0;
            double bosScore = (bosUp || bosDown) ? 0.45 : 0.0;
            double candleScore = (c0 > o0 || c0 < o0) ? 0.15 : 0.0;

            if (trendUp && pullLong && bosUp)
            {
                return new SetupResult
                {
                    Action = SetupAction.BUY,
                    Confidence = Clamp01(0.25 + distScore * 0.25 + bosScore + candleScore),
                    Reason = "trend_up+pullback+bos"
                };
            }

            if (trendDown && pullShort && bosDown)
            {
                return new SetupResult
                {
                    Action = SetupAction.SELL,
                    Confidence = Clamp01(0.25 + distScore * 0.25 + bosScore + candleScore),
                    Reason = "trend_down+pullback+bos"
                };
            }

            return new SetupResult { Action = SetupAction.NONE, Confidence = 0.0, Reason = "no_setup" };
        }

        private void ExecuteSetup(SetupResult setup)
        {
            int qty = Math.Max(1, Qty);
            int sl = Math.Max(0, StopLossTicks);
            int tp = Math.Max(0, TakeProfitTicks);

            var mp = Position != null ? Position.MarketPosition : MarketPosition.Flat;

            // One position policy: if opposite, flatten first and wait (no flip same bar).
            if (setup.Action == SetupAction.BUY && mp == MarketPosition.Short)
            {
                ExitShort("bt_exit_short", "bt_sell");
                _cooldownLeft = Math.Max(0, CooldownBars);
                ExplainTrade("FLATTEN short before BUY");
                return;
            }
            if (setup.Action == SetupAction.SELL && mp == MarketPosition.Long)
            {
                ExitLong("bt_exit_long", "bt_buy");
                _cooldownLeft = Math.Max(0, CooldownBars);
                ExplainTrade("FLATTEN long before SELL");
                return;
            }

            if (mp != MarketPosition.Flat)
            {
                ExplainWait("in_position");
                return;
            }

            if (setup.Action == SetupAction.BUY)
            {
                string signal = "bt_buy";
                if (sl > 0) SetStopLoss(signal, CalculationMode.Ticks, sl, false);
                if (tp > 0) SetProfitTarget(signal, CalculationMode.Ticks, tp);
                EnterLong(qty, signal);
                _cooldownLeft = Math.Max(0, CooldownBars);
                _tradesThisSession++;
                _tradesTaken++;
                ExplainTrade("BUY " + setup.Reason + " conf=" + setup.Confidence.ToString("0.00", CultureInfo.InvariantCulture));
                return;
            }

            if (setup.Action == SetupAction.SELL)
            {
                string signal = "bt_sell";
                if (sl > 0) SetStopLoss(signal, CalculationMode.Ticks, sl, false);
                if (tp > 0) SetProfitTarget(signal, CalculationMode.Ticks, tp);
                EnterShort(qty, signal);
                _cooldownLeft = Math.Max(0, CooldownBars);
                _tradesThisSession++;
                _tradesTaken++;
                ExplainTrade("SELL " + setup.Reason + " conf=" + setup.Confidence.ToString("0.00", CultureInfo.InvariantCulture));
            }
        }

        private void ExplainWait(string reason)
        {
            if (!EnableLogging) return;
            if (CurrentBar < 0) return;

            bool should = false;
            if ((reason ?? "") != _lastWaitReason) should = true;
            if ((CurrentBar - _lastExplainBar) >= EXPLAIN_EVERY_N_BARS) should = true;
            if (!should) return;

            _lastWaitReason = reason ?? "";
            _lastExplainBar = CurrentBar;
            Print("WAIT: " + _lastWaitReason);
        }

        private void ExplainTrade(string msg)
        {
            if (!EnableLogging) return;
            Print("TRADE: " + (msg ?? ""));
        }

        private static double Clamp01(double v)
        {
            if (v < 0.0) return 0.0;
            if (v > 1.0) return 1.0;
            return v;
        }

        private void EmitSummary()
        {
            try
            {
                double realized = 0.0;
                int trades = 0;
                double winRate = 0.0;
                double avgTrade = 0.0;
                double expectancy = 0.0;
                double pf = 0.0;

                try
                {
                    realized = SystemPerformance.AllTrades.TradesPerformance.Currency.CumProfit;
                    trades = SystemPerformance.AllTrades.Count;
                    winRate = SystemPerformance.AllTrades.TradesPerformance.Percent.Win;
                    avgTrade = SystemPerformance.AllTrades.TradesPerformance.Currency.AvgTrade;
                    expectancy = SystemPerformance.AllTrades.TradesPerformance.Currency.Expectancy;
                    pf = SystemPerformance.AllTrades.TradesPerformance.ProfitFactor;
                }
                catch { }

                var sb = new StringBuilder();
                sb.Append("{\"type\":\"BACKTEST_SUMMARY\"");
                sb.Append(",\"runId\":\"").Append(_runId ?? "").Append("\"");
                sb.Append(",\"strategy\":\"").Append(Name.Replace("\"", "")).Append("\"");
                sb.Append(",\"netPnL\":").Append(realized.ToString("R", CultureInfo.InvariantCulture));
                sb.Append(",\"maxDD\":").Append(_maxDrawdown.ToString("R", CultureInfo.InvariantCulture));
                sb.Append(",\"trades\":").Append(trades.ToString(CultureInfo.InvariantCulture));
                sb.Append(",\"winrate\":").Append(winRate.ToString("R", CultureInfo.InvariantCulture));
                sb.Append(",\"profitFactor\":").Append(pf.ToString("R", CultureInfo.InvariantCulture));
                sb.Append(",\"avgTrade\":").Append(avgTrade.ToString("R", CultureInfo.InvariantCulture));
                sb.Append(",\"expectancy\":").Append(expectancy.ToString("R", CultureInfo.InvariantCulture));

                sb.Append(",\"signals_seen\":").Append(_signalsSeen.ToString(CultureInfo.InvariantCulture));
                sb.Append(",\"trades_taken\":").Append(_tradesTaken.ToString(CultureInfo.InvariantCulture));
                sb.Append(",\"skipped_confidence\":").Append(_skippedConfidence.ToString(CultureInfo.InvariantCulture));
                sb.Append(",\"skipped_atr\":").Append(_skippedAtr.ToString(CultureInfo.InvariantCulture));
                sb.Append(",\"skipped_cooldown\":").Append(_skippedCooldown.ToString(CultureInfo.InvariantCulture));
                sb.Append(",\"skipped_session\":").Append(_skippedSession.ToString(CultureInfo.InvariantCulture));
                sb.Append(",\"skipped_max_trades\":").Append(_skippedMaxTrades.ToString(CultureInfo.InvariantCulture));
                sb.Append(",\"skipped_hard_stop\":").Append(_skippedHardStop.ToString(CultureInfo.InvariantCulture));

                sb.Append(",\"params\":{");
                sb.Append("\"Qty\":").Append(Qty.ToString(CultureInfo.InvariantCulture)).Append(",");
                sb.Append("\"SL\":").Append(StopLossTicks.ToString(CultureInfo.InvariantCulture)).Append(",");
                sb.Append("\"TP\":").Append(TakeProfitTicks.ToString(CultureInfo.InvariantCulture)).Append(",");
                sb.Append("\"MinAtrTicks\":").Append(MinAtrTicks.ToString(CultureInfo.InvariantCulture)).Append(",");
                sb.Append("\"CooldownBars\":").Append(CooldownBars.ToString(CultureInfo.InvariantCulture)).Append(",");
                sb.Append("\"MaxTradesPerSession\":").Append(MaxTradesPerSession.ToString(CultureInfo.InvariantCulture)).Append(",");
                sb.Append("\"SessionMode\":\"").Append(Session.ToString()).Append("\",");
                sb.Append("\"MinConfidence\":").Append(MinConfidence.ToString("R", CultureInfo.InvariantCulture)).Append(",");
                sb.Append("\"MaxLossUsd\":").Append(MaxLossUsd.ToString("R", CultureInfo.InvariantCulture)).Append(",");
                sb.Append("\"Start\":").Append(StartTimeHHmm.ToString(CultureInfo.InvariantCulture)).Append(",");
                sb.Append("\"End\":").Append(EndTimeHHmm.ToString(CultureInfo.InvariantCulture)).Append(",");
                sb.Append("\"EmaTrendLen\":").Append(EmaTrendLen.ToString(CultureInfo.InvariantCulture)).Append(",");
                sb.Append("\"EmaPullbackLen\":").Append(EmaPullbackLen.ToString(CultureInfo.InvariantCulture)).Append(",");
                sb.Append("\"BosLookback\":").Append(BosLookback.ToString(CultureInfo.InvariantCulture));
                sb.Append("}}");

                Print(sb.ToString());
            }
            catch { }
        }
    }
}


#region Using declarations
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Globalization;
using System.IO;
using System.Net.WebSockets;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using Timer = System.Timers.Timer;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.NinjaScript;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class BridgePuppet : Strategy
    {
        #region Minimal JSON (no external deps)
        private static class MiniJson
        {
            public static string GetString(string json, string key)
            {
                if (string.IsNullOrWhiteSpace(json) || string.IsNullOrWhiteSpace(key)) return null;

                var m = Regex.Match(json,
                    "\"" + Regex.Escape(key) + "\"\\s*:\\s*\"(?<v>(?:\\\\.|[^\"\\\\])*)\"",
                    RegexOptions.CultureInvariant);

                if (!m.Success) return null;
                return Unescape(m.Groups["v"].Value);
            }

            public static int GetInt(string json, string key, int fallback = 0)
            {
                if (string.IsNullOrWhiteSpace(json) || string.IsNullOrWhiteSpace(key)) return fallback;

                var m = Regex.Match(json,
                    "\"" + Regex.Escape(key) + "\"\\s*:\\s*(?<v>-?\\d+)",
                    RegexOptions.CultureInvariant);

                if (!m.Success) return fallback;

                int v;
                return int.TryParse(m.Groups["v"].Value, NumberStyles.Integer, CultureInfo.InvariantCulture, out v)
                    ? v
                    : fallback;
            }

            public static string Escape(string s)
            {
                if (s == null) return "";
                return s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n");
            }

            private static string Unescape(string s)
            {
                if (s == null) return null;
                return s.Replace("\\\"", "\"").Replace("\\\\", "\\").Replace("\\n", "\n").Replace("\\r", "\r");
            }

            public static string BuildAck(string id, string status, string message, string ts, Cmd cmd = null)
            {
                string details = "";
                if (cmd != null)
                {
                    if (!string.IsNullOrWhiteSpace(cmd.Action))
                        details += ",\"action\":\"" + Escape(cmd.Action) + "\"";
                    if (cmd.Qty > 0)
                        details += ",\"qty\":" + cmd.Qty.ToString(CultureInfo.InvariantCulture);
                    if (cmd.SlTicks > 0)
                        details += ",\"slTicks\":" + cmd.SlTicks.ToString(CultureInfo.InvariantCulture);
                    if (cmd.TpTicks > 0)
                        details += ",\"tpTicks\":" + cmd.TpTicks.ToString(CultureInfo.InvariantCulture);
                    if (!string.IsNullOrWhiteSpace(cmd.Tag))
                        details += ",\"tag\":\"" + Escape(cmd.Tag) + "\"";
                    if (!string.IsNullOrWhiteSpace(cmd.Symbol))
                        details += ",\"symbol\":\"" + Escape(cmd.Symbol) + "\"";
                }
                return "{"
                    + "\"type\":\"ACK\","
                    + "\"payload\":{"
                        + "\"id\":\"" + Escape(id) + "\","
                        + "\"status\":\"" + Escape(status) + "\","
                        + "\"message\":\"" + Escape(message ?? "") + "\","
                        + "\"ts\":\"" + Escape(ts) + "\""
                        + details
                    + "}"
                + "}";
            }

            public static string BuildAckV2(string botId, long seq, string id, string status, string message, string sendTsUtc, Cmd cmd = null)
            {
                string details = "";
                if (cmd != null)
                {
                    if (!string.IsNullOrWhiteSpace(cmd.Action))
                        details += ",\"action\":\"" + Escape(cmd.Action) + "\"";
                    if (cmd.Qty > 0)
                        details += ",\"qty\":" + cmd.Qty.ToString(CultureInfo.InvariantCulture);
                    if (cmd.SlTicks > 0)
                        details += ",\"slTicks\":" + cmd.SlTicks.ToString(CultureInfo.InvariantCulture);
                    if (cmd.TpTicks > 0)
                        details += ",\"tpTicks\":" + cmd.TpTicks.ToString(CultureInfo.InvariantCulture);
                    if (!string.IsNullOrWhiteSpace(cmd.Tag))
                        details += ",\"tag\":\"" + Escape(cmd.Tag) + "\"";
                    if (!string.IsNullOrWhiteSpace(cmd.Symbol))
                        details += ",\"symbol\":\"" + Escape(cmd.Symbol) + "\"";
                }

                return "{"
                    + "\"type\":\"ACK\","
                    + "\"v\":2,"
                    + "\"source\":\"NINJA_WS\","
                    + "\"botId\":\"" + Escape(botId ?? "") + "\","
                    + "\"seq\":" + seq.ToString(CultureInfo.InvariantCulture) + ","
                    + "\"send_ts_utc\":\"" + Escape(sendTsUtc) + "\","
                    + "\"payload\":{"
                        + "\"id\":\"" + Escape(id ?? "") + "\","
                        + "\"status\":\"" + Escape(status ?? "") + "\","
                        + "\"message\":\"" + Escape(message ?? "") + "\","
                        + "\"ts\":\"" + Escape(sendTsUtc) + "\""
                        + details
                    + "}"
                + "}";
            }

            public static string BuildBar(string timestamp, string symbol, string timeframe,
                                          double o, double h, double l, double c, int vol, string mode)
            {
                string Open = o.ToString("R", CultureInfo.InvariantCulture);
                string High = h.ToString("R", CultureInfo.InvariantCulture);
                string Low = l.ToString("R", CultureInfo.InvariantCulture);
                string Close = c.ToString("R", CultureInfo.InvariantCulture);

                return "{"
                    + "\"type\":\"BAR_DATA\","
                    + "\"payload\":{"
                        + "\"timestamp\":\"" + Escape(timestamp) + "\","
                        + "\"symbol\":\"" + Escape(symbol) + "\","
                        + "\"timeframe\":\"" + Escape(timeframe) + "\","
                        + "\"open\":" + Open + ","
                        + "\"high\":" + High + ","
                        + "\"low\":" + Low + ","
                        + "\"close\":" + Close + ","
                        + "\"volume\":" + vol.ToString(CultureInfo.InvariantCulture) + ","
                        + "\"mode\":\"" + Escape(mode) + "\""
                    + "}"
                + "}";
            }

            public static string BuildMonitor(string ts,
                                              string mode,
                                              string wsState,
                                              string strategyState,
                                              int sendIndex,
                                              string lastBarObservedUtc,
                                              string lastBarSentUtc,
                                              string lastWsSendUtc,
                                              double? observedAgeSec,
                                              double? sentAgeSec,
                                              double? wsSendAgeSec,
                                              long sendCount,
                                              long skipCount)
            {
                string observedAge = observedAgeSec.HasValue
                    ? observedAgeSec.Value.ToString("0.0", CultureInfo.InvariantCulture)
                    : "null";
                string sentAge = sentAgeSec.HasValue
                    ? sentAgeSec.Value.ToString("0.0", CultureInfo.InvariantCulture)
                    : "null";
                string wsAge = wsSendAgeSec.HasValue
                    ? wsSendAgeSec.Value.ToString("0.0", CultureInfo.InvariantCulture)
                    : "null";

                string observedUtc = string.IsNullOrWhiteSpace(lastBarObservedUtc)
                    ? "null"
                    : "\"" + Escape(lastBarObservedUtc) + "\"";
                string sentUtc = string.IsNullOrWhiteSpace(lastBarSentUtc)
                    ? "null"
                    : "\"" + Escape(lastBarSentUtc) + "\"";
                string wsUtc = string.IsNullOrWhiteSpace(lastWsSendUtc)
                    ? "null"
                    : "\"" + Escape(lastWsSendUtc) + "\"";

                return "{"
                    + "\"type\":\"MONITOR\","
                    + "\"payload\":{"
                        + "\"ts\":\"" + Escape(ts) + "\","
                        + "\"mode\":\"" + Escape(mode ?? "") + "\","
                        + "\"wsState\":\"" + Escape(wsState ?? "") + "\","
                        + "\"strategyState\":\"" + Escape(strategyState ?? "") + "\","
                        + "\"sendIndex\":" + sendIndex.ToString(CultureInfo.InvariantCulture) + ","
                        + "\"lastBarObservedUtc\":" + observedUtc + ","
                        + "\"lastBarSentUtc\":" + sentUtc + ","
                        + "\"lastWsSendUtc\":" + wsUtc + ","
                        + "\"observedAgeSec\":" + observedAge + ","
                        + "\"sentAgeSec\":" + sentAge + ","
                        + "\"wsSendAgeSec\":" + wsAge + ","
                        + "\"sendCount\":" + sendCount.ToString(CultureInfo.InvariantCulture) + ","
                        + "\"skipCount\":" + skipCount.ToString(CultureInfo.InvariantCulture)
                    + "}"
                + "}";
            }

            public static string BuildMonitorV2(
                string botId, long seq, string sendTsUtc,
                string ntMode, string wsState, string strategyState,
                int outHiDepth, int outLoDepth, long outDropLo,
                string lastBarObservedUtc, string lastBarSentUtc, string lastWsSendUtc,
                double? observedAgeSec, double? sentAgeSec, double? wsSendAgeSec,
                long sendCount, long skipCount,
                bool execEnabled, bool isStrategyAnalyzer
            )
            {
                string observedUtc = string.IsNullOrWhiteSpace(lastBarObservedUtc) ? "null" : "\"" + Escape(lastBarObservedUtc) + "\"";
                string sentUtc = string.IsNullOrWhiteSpace(lastBarSentUtc) ? "null" : "\"" + Escape(lastBarSentUtc) + "\"";
                string wsUtc = string.IsNullOrWhiteSpace(lastWsSendUtc) ? "null" : "\"" + Escape(lastWsSendUtc) + "\"";

                string observedAge = observedAgeSec.HasValue ? observedAgeSec.Value.ToString("0.0", CultureInfo.InvariantCulture) : "null";
                string sentAge = sentAgeSec.HasValue ? sentAgeSec.Value.ToString("0.0", CultureInfo.InvariantCulture) : "null";
                string wsAge = wsSendAgeSec.HasValue ? wsSendAgeSec.Value.ToString("0.0", CultureInfo.InvariantCulture) : "null";

                return "{"
                    + "\"type\":\"MONITOR\","
                    + "\"v\":2,"
                    + "\"source\":\"NINJA_WS\","
                    + "\"botId\":\"" + Escape(botId ?? "") + "\","
                    + "\"seq\":" + seq.ToString(CultureInfo.InvariantCulture) + ","
                    + "\"send_ts_utc\":\"" + Escape(sendTsUtc) + "\","
                    + "\"payload\":{"
                        + "\"ts\":\"" + Escape(sendTsUtc) + "\","
                        + "\"nt_mode\":\"" + Escape(ntMode ?? "") + "\","
                        + "\"wsState\":\"" + Escape(wsState ?? "") + "\","
                        + "\"strategyState\":\"" + Escape(strategyState ?? "") + "\","
                        + "\"outHiDepth\":" + outHiDepth.ToString(CultureInfo.InvariantCulture) + ","
                        + "\"outLoDepth\":" + outLoDepth.ToString(CultureInfo.InvariantCulture) + ","
                        + "\"outDropLo\":" + outDropLo.ToString(CultureInfo.InvariantCulture) + ","
                        + "\"lastBarObservedUtc\":" + observedUtc + ","
                        + "\"lastBarSentUtc\":" + sentUtc + ","
                        + "\"lastWsSendUtc\":" + wsUtc + ","
                        + "\"observedAgeSec\":" + observedAge + ","
                        + "\"sentAgeSec\":" + sentAge + ","
                        + "\"wsSendAgeSec\":" + wsAge + ","
                        + "\"sendCount\":" + sendCount.ToString(CultureInfo.InvariantCulture) + ","
                        + "\"skipCount\":" + skipCount.ToString(CultureInfo.InvariantCulture) + ","
                        + "\"exec_enabled\":" + (execEnabled ? "true" : "false") + ","
                        + "\"is_strategy_analyzer\":" + (isStrategyAnalyzer ? "true" : "false")
                    + "}"
                + "}";
            }

            public static string BuildBarDataV2(
                string botId,
                long seq,
                string sendTsUtc,
                string barTsUtc,
                string symbol,
                string timeframe,
                double o, double h, double l, double c,
                long vol,
                string ntMode,
                bool execEnabled,
                bool isStrategyAnalyzer,
                int barsInProgress
            )
            {
                return "{"
                    + "\"type\":\"BAR_DATA\","
                    + "\"v\":2,"
                    + "\"source\":\"NINJA_WS\","
                    + "\"botId\":\"" + Escape(botId ?? "") + "\","
                    + "\"seq\":" + seq.ToString(CultureInfo.InvariantCulture) + ","
                    + "\"send_ts_utc\":\"" + Escape(sendTsUtc) + "\","
                    + "\"payload\":{"
                        + "\"bar_ts_utc\":\"" + Escape(barTsUtc) + "\","
                        + "\"timestamp\":\"" + Escape(barTsUtc) + "\","
                        + "\"symbol\":\"" + Escape(symbol ?? "") + "\","
                        + "\"timeframe\":\"" + Escape(timeframe ?? "") + "\","
                        + "\"open\":" + o.ToString("R", CultureInfo.InvariantCulture) + ","
                        + "\"high\":" + h.ToString("R", CultureInfo.InvariantCulture) + ","
                        + "\"low\":" + l.ToString("R", CultureInfo.InvariantCulture) + ","
                        + "\"close\":" + c.ToString("R", CultureInfo.InvariantCulture) + ","
                        + "\"volume\":" + vol.ToString(CultureInfo.InvariantCulture) + ","
                        + "\"nt_mode\":\"" + Escape(ntMode ?? "") + "\","
                        + "\"exec_enabled\":" + (execEnabled ? "true" : "false") + ","
                        + "\"is_strategy_analyzer\":" + (isStrategyAnalyzer ? "true" : "false") + ","
                        + "\"bars_in_progress\":" + barsInProgress.ToString(CultureInfo.InvariantCulture)
                    + "}"
                + "}";
            }
        }

        private class Cmd
        {
            public string Id;
            public string Action;
            public int Qty;
            public int SlTicks;
            public int TpTicks;
            public string Tag;
            public string Symbol;
            public DateTime ReceivedAtUtc;
        }
        #endregion

        private ClientWebSocket _ws;
        private CancellationTokenSource _cts;
        private Task _wsWorker;

        private readonly ConcurrentQueue<Cmd> _cmdQueue = new ConcurrentQueue<Cmd>();
        private readonly HashSet<string> _processed = new HashSet<string>();
        private readonly Queue<string> _processedOrder = new Queue<string>();
        private const int MAX_PROCESSED = 5000;

        // Outbound queues (priority)
        // - High: ACK / MONITOR / TRADE_EVENT
        // - Low:  BAR_DATA (droppable under congestion)
        private readonly ConcurrentQueue<string> _outHi = new ConcurrentQueue<string>();
        private readonly ConcurrentQueue<string> _outLo = new ConcurrentQueue<string>();
        private readonly SemaphoreSlim _outSignal = new SemaphoreSlim(0, int.MaxValue);
        private int _outHiDepth = 0;
        private int _outLoDepth = 0;
        private long _outDropLo = 0;
        private const int MAX_OUT_LO = 2000;
        private const int MAX_OUT_HI = 500;
        private const int SEND_LOOP_IDLE_MS = 250;

        private const int WS_RETRY_BASE_MS = 1000;
        private const int WS_RETRY_MAX_MS = 30000;
        private int _wsReconnectAttempt = 0;

        private long _barSeq = 0;
        private int _lastVolumeValue = int.MinValue;
        private long _volumeWarnSeq = 0;

        private int _liveBarsIndex = -1;
        private Timer _monitorTimer;
        private readonly object _monitorTimerLock = new object();
        private DateTime _lastMonitorUtc = DateTime.MinValue;
        private DateTime _lastBarObservedUtc = DateTime.MinValue;
        private DateTime _lastBarSentUtc = DateTime.MinValue;
        private DateTime _lastWsSendUtc = DateTime.MinValue;
        private long _barSendCount = 0;
        private long _barSkipCount = 0;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "BridgePuppet";
                Description = "Bridge: uses WebSockets to connect to backend and executes commands.";
                Calculate = Calculate.OnEachTick;
                BarsRequiredToTrade = 1;

                ServerUrl = "localhost:8000";
                BotId = "bot-1";
                ApiKey = "";

                EnableReceiveCommands = true;
                EnableSendBars = true;
                // Backtest/replay can flood; keep off by default.
                SendBarsInBacktest = false;
                EnableLiveExecution = false;
                SendOnlyClosedBars = true;

                DefaultQty = 1;
                MaxContracts = 50;
                AllowReversal = true;

                DefaultStopLossTicks = 0;
                DefaultTakeProfitTicks = 0;

                ForceTimeframeText = "";
                ForceSymbol = "";
                LiveBarSeconds = 1;

                EnableLogging = true;
                EnableVolumeDiagnostics = true;
                EnableMonitor = true;
                MonitorIntervalSec = 10;
            }
            else if (State == State.Configure)
            {
                if (LiveBarSeconds > 0)
                {
                    AddDataSeries(BarsPeriodType.Second, LiveBarSeconds);
                    _liveBarsIndex = 1;
                }
            }
            else if (State == State.DataLoaded)
            {
                _cts = new CancellationTokenSource();
                _lastMonitorUtc = DateTime.UtcNow;
                StartMonitorTimer();
                if (EnableLogging) Print("BridgePuppet loaded. Server: " + ServerUrl);
            }
            else if (State == State.Historical)
            {
                if ((EnableReceiveCommands || EnableSendBars) && SendBarsInBacktest)
                    StartWsWorker();
            }
            else if (State == State.Realtime)
            {
                if (EnableLogging) Print("BridgePuppet -> Realtime");

                if (EnableReceiveCommands || EnableSendBars)
                    StartWsWorker();
            }
            else if (State == State.Terminated)
            {
                try { _cts?.Cancel(); } catch { }
                try { _ws?.Abort(); } catch { }
                try { _ws?.Dispose(); } catch { }
                StopMonitorTimer();

                if (EnableLogging) Print("BridgePuppet terminated");
            }
        }

        private bool IsLiveNow()
        {
            return State == State.Realtime && !IsInStrategyAnalyzer;
        }

        private string CurrentMode()
        {
            if (IsInStrategyAnalyzer) return "BACKTEST";
            if (State == State.Historical) return "BACKTEST";
            if (State == State.Realtime) return "LIVE";
            return "UNKNOWN";
        }

        protected override void OnBarUpdate()
        {
            int sendIndex = ResolveSendIndex();
            if (sendIndex < 0) return;
            if (BarsInProgress == 0 && IsLiveNow() && IsFirstTickOfBar)
                DrainQueue();

            if (BarsInProgress != sendIndex) return;

            bool live = IsLiveNow();
            if (!live && !SendBarsInBacktest) return;

            // Send only on bar boundaries to avoid flooding and keep determinism.
            if (!IsFirstTickOfBar)
            {
                Interlocked.Increment(ref _barSkipCount);
                return;
            }

            _lastBarObservedUtc = DateTime.UtcNow;
            LogVolumeSnapshot(sendIndex);

            int barsAgo = SendOnlyClosedBars ? 1 : 0;
            if (CurrentBars[sendIndex] < (barsAgo + 1)) return;

            SendBarOverWs(sendIndex, barsAgo);
        }

        private int ResolveSendIndex()
        {
            if (_liveBarsIndex > 0 && CurrentBars != null && CurrentBars.Length > _liveBarsIndex)
            {
                if (CurrentBars[_liveBarsIndex] >= 1)
                    return _liveBarsIndex;
            }
            if (CurrentBars != null && CurrentBars.Length > 0 && CurrentBars[0] >= 1)
                return 0;
            return -1;
        }

        // Backtest timer removed on purpose: historical/replay can flood.

        private void StartMonitorTimer()
        {
            lock (_monitorTimerLock)
            {
                if (_monitorTimer != null) return;
                int intervalSec = Math.Max(1, MonitorIntervalSec);
                _monitorTimer = new Timer(intervalSec * 1000);
                _monitorTimer.AutoReset = true;
                _monitorTimer.Elapsed += OnMonitorTimerElapsed;
                _monitorTimer.Start();
            }
        }

        private void StopMonitorTimer()
        {
            lock (_monitorTimerLock)
            {
                if (_monitorTimer == null) return;
                try
                {
                    _monitorTimer.Stop();
                    _monitorTimer.Elapsed -= OnMonitorTimerElapsed;
                    _monitorTimer.Dispose();
                }
                catch { }
                _monitorTimer = null;
            }
        }

        private void OnMonitorTimerElapsed(object sender, System.Timers.ElapsedEventArgs e)
        {
            try
            {
                TriggerCustomEvent(_ => MonitorHeartbeat(), null);
            }
            catch { }
        }

        private void MonitorHeartbeat()
        {
            if (!EnableMonitor) return;
            EmitMonitorLine();
        }

        private void EmitMonitorLine()
        {
            var now = DateTime.UtcNow;
            if ((now - _lastMonitorUtc).TotalSeconds < Math.Max(1, MonitorIntervalSec) - 0.1)
                return;

            _lastMonitorUtc = now;
            string wsState = _ws != null ? _ws.State.ToString() : "null";
            string mode = CurrentMode();
            int sendIndex = ResolveSendIndex();
            string observedUtc = _lastBarObservedUtc == DateTime.MinValue
                ? null
                : _lastBarObservedUtc.ToString("o", CultureInfo.InvariantCulture);
            string sentUtc = _lastBarSentUtc == DateTime.MinValue
                ? null
                : _lastBarSentUtc.ToString("o", CultureInfo.InvariantCulture);
            string wsUtc = _lastWsSendUtc == DateTime.MinValue
                ? null
                : _lastWsSendUtc.ToString("o", CultureInfo.InvariantCulture);
            double? observedAge = _lastBarObservedUtc == DateTime.MinValue
                ? (double?)null
                : (DateTime.UtcNow - _lastBarObservedUtc).TotalSeconds;
            double? sentAge = _lastBarSentUtc == DateTime.MinValue
                ? (double?)null
                : (DateTime.UtcNow - _lastBarSentUtc).TotalSeconds;
            double? wsAge = _lastWsSendUtc == DateTime.MinValue
                ? (double?)null
                : (DateTime.UtcNow - _lastWsSendUtc).TotalSeconds;

            if (EnableLogging)
            {
                Print("MONITOR mode=" + mode
                    + " state=" + State
                    + " ws=" + wsState
                    + " sendIndex=" + sendIndex.ToString(CultureInfo.InvariantCulture)
                    + " observedAgeSec=" + FormatAgeSeconds(_lastBarObservedUtc)
                    + " sentAgeSec=" + FormatAgeSeconds(_lastBarSentUtc)
                    + " wsSendAgeSec=" + FormatAgeSeconds(_lastWsSendUtc)
                    + " sendCount=" + _barSendCount.ToString(CultureInfo.InvariantCulture)
                    + " skipCount=" + _barSkipCount.ToString(CultureInfo.InvariantCulture)
                    + " outDropLo=" + _outDropLo.ToString(CultureInfo.InvariantCulture));
            }

            string sendTsUtc = now.ToString("o", CultureInfo.InvariantCulture);
            long seq = Interlocked.Increment(ref _barSeq);
            var monitorJson = MiniJson.BuildMonitorV2(
                BotId,
                seq,
                sendTsUtc,
                mode,
                wsState,
                State.ToString(),
                Math.Max(0, _outHiDepth),
                Math.Max(0, _outLoDepth),
                _outDropLo,
                observedUtc,
                sentUtc,
                wsUtc,
                observedAge,
                sentAge,
                wsAge,
                _barSendCount,
                _barSkipCount,
                EnableLiveExecution,
                IsInStrategyAnalyzer
            );
            EnqueueHigh(monitorJson);
        }

        private string FormatAgeSeconds(DateTime utc)
        {
            if (utc == DateTime.MinValue) return "n/a";
            var sec = (DateTime.UtcNow - utc).TotalSeconds;
            return sec.ToString("0.0", CultureInfo.InvariantCulture);
        }

        private void StartWsWorker()
        {
            if (_wsWorker != null || _cts == null) return;

            _wsWorker = Task.Run(async () =>
            {
                var ct = _cts.Token;
                if (EnableLogging) Print("WebSocket worker started.");

                while (!ct.IsCancellationRequested)
                {
                    try
                    {
                        using (_ws = new ClientWebSocket())
                        {
                            var url = GetWsUrl();
                            if (!string.IsNullOrEmpty(ApiKey))
                            {
                                _ws.Options.SetRequestHeader("X-API-Key", ApiKey);
                            }
                            try { _ws.Options.KeepAliveInterval = TimeSpan.FromSeconds(15); } catch { }
                            
                            if (EnableLogging) Print("Connecting to WebSocket: " + url);
                            await _ws.ConnectAsync(url, ct).ConfigureAwait(false);
                            if (EnableLogging) Print("WebSocket connected.");
                            _wsReconnectAttempt = 0;

                            // Start a single send loop for this connection (no per-message Task.Run).
                            var sendTask = SendLoop(_ws, ct);

                            // Receive loop blocks until server closes.
                            await ReceiveLoop(_ws, ct);

                            try { await sendTask.ConfigureAwait(false); } catch { }
                        }
                    }
                    catch (WebSocketException wsex)
                    {
                        if (EnableLogging) Print($"WebSocket error: {wsex.Message}. Reconnecting in 5s...");
                    }
                    catch (TaskCanceledException) { break; } // Shutdown
                    catch (Exception ex)
                    {
                        if (EnableLogging) Print($"WebSocket worker error: {ex.Message}. Reconnecting in 5s...");
                    }
                    finally
                    {
                        _ws?.Dispose();
                    }
                    
                    if (!ct.IsCancellationRequested)
                    {
                        _wsReconnectAttempt = Math.Min(_wsReconnectAttempt + 1, 10);
                        var delay = Math.Min(WS_RETRY_MAX_MS, WS_RETRY_BASE_MS * (int)Math.Pow(2, Math.Min(_wsReconnectAttempt, 6)));
                        if (EnableLogging) Print($"WebSocket reconnect in {delay}ms (attempt {_wsReconnectAttempt})");
                        await Task.Delay(delay, ct).ConfigureAwait(false);
                    }
                }
                if (EnableLogging) Print("WebSocket worker stopped.");
            }, _cts.Token);
        }

        private async Task ReceiveLoop(ClientWebSocket ws, CancellationToken ct)
        {
            var buffer = new byte[1024 * 4];
            
            while (ws.State == WebSocketState.Open && !ct.IsCancellationRequested)
            {
                using (var ms = new MemoryStream())
                {
                    WebSocketReceiveResult result;
                    do
                    {
                        result = await ws.ReceiveAsync(new ArraySegment<byte>(buffer), ct);
                        ms.Write(buffer, 0, result.Count);
                    } while (!result.EndOfMessage);

                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        if (EnableLogging) Print("WebSocket closed by server.");
                        break;
                    }

                    ms.Seek(0, SeekOrigin.Begin);
                    var body = Encoding.UTF8.GetString(ms.ToArray());
                    
                    var cmd = ParseCommand(body);
                    if (cmd == null || string.IsNullOrWhiteSpace(cmd.Action) || cmd.Action.Trim().ToUpperInvariant() == "NONE")
                    {
                        continue;
                    }

                    if (!string.IsNullOrEmpty(cmd.Id))
                    {
                        bool already;
                        lock (_processed)
                        {
                            already = _processed.Contains(cmd.Id);
                            if (!already)
                            {
                                _processed.Add(cmd.Id);
                                _processedOrder.Enqueue(cmd.Id);
                                while (_processedOrder.Count > MAX_PROCESSED)
                                {
                                    var old = _processedOrder.Dequeue();
                                    _processed.Remove(old);
                                }
                            }
                        }

                        if (already)
                        {
                            SendAckOverWs(cmd.Id, "DUPLICATE_IGNORED", "already processed", cmd);
                            continue;
                        }
                    }

                    SendAckOverWs(cmd.Id, "RECEIVED", cmd.Action, cmd);
                    _cmdQueue.Enqueue(cmd);

                    // Execute immediately on the NinjaScript thread to avoid waiting for bar close.
                    try
                    {
                        TriggerCustomEvent(_ => DrainQueue(), null);
                    }
                    catch (Exception ex)
                    {
                        if (EnableLogging) Print("TriggerCustomEvent failed: " + ex.Message);
                    }
                }
            }
        }

        private void DrainQueue()
        {
            if (!IsLiveNow()) return;

            int maxPerTick = 10;
            while (maxPerTick-- > 0 && _cmdQueue.TryDequeue(out var cmd))
            {
                try
                {
                    HandleCommand(cmd);
                }
                catch (Exception ex)
                {
                    if (EnableLogging) Print("HandleCommand error: " + ex.Message);
                    SendAckOverWs(cmd?.Id, "ERROR", ex.Message, cmd);
                }
            }
        }

        private void HandleCommand(Cmd c)
        {
            if (c == null) return;

            string action = (c.Action ?? "").Trim().ToUpperInvariant();
            if (string.IsNullOrEmpty(action) || action == "NONE") return;

            if (!EnableLiveExecution)
            {
                SendAckOverWs(c.Id, "IGNORED", AppendLatency(c, "EnableLiveExecution=false"), c);
                return;
            }

            int qty = c.Qty > 0 ? c.Qty : DefaultQty;
            qty = Math.Min(qty, MaxContracts);

            int sl = c.SlTicks > 0 ? c.SlTicks : DefaultStopLossTicks;
            int tp = c.TpTicks > 0 ? c.TpTicks : DefaultTakeProfitTicks;

            if (!AllowReversal)
            {
                if (Position.MarketPosition == MarketPosition.Long && action == "SELL") { SendAckOverWs(c.Id, "IGNORED", "AllowReversal=false"); return; }
                if (Position.MarketPosition == MarketPosition.Short && action == "BUY") { SendAckOverWs(c.Id, "IGNORED", "AllowReversal=false"); return; }
            }

            string cmdId = string.IsNullOrWhiteSpace(c.Id) ? $"cmd_{DateTime.UtcNow.Ticks}" : c.Id.Trim();
            string tag = string.IsNullOrWhiteSpace(c.Tag) ? "bp" : c.Tag.Trim();
            string signal = $"{tag}__{cmdId}__{DateTime.UtcNow.Ticks}";

            if (action == "FLATTEN" || action == "CLOSE")
            {
                if (Position.MarketPosition == MarketPosition.Long)
                {
                    ExitLong();
                    SendAckOverWs(cmdId, "SENT", AppendLatency(c, "flatten"), c);
                }
                else if (Position.MarketPosition == MarketPosition.Short)
                {
                    ExitShort();
                    SendAckOverWs(cmdId, "SENT", AppendLatency(c, "flatten"), c);
                }
                else
                {
                    if (EnableLogging) Print("FLATTEN ignored: no open position");
                    SendAckOverWs(cmdId, "IGNORED", AppendLatency(c, "no open position"), c);
                }
                return;
            }

            if (sl > 0) SetStopLoss(signal, CalculationMode.Ticks, sl, false);
            if (tp > 0) SetProfitTarget(signal, CalculationMode.Ticks, tp);

            if (action == "BUY")
            {
                EnterLong(qty, signal);
                SendAckOverWs(cmdId, "SENT", AppendLatency(c, $"BUY qty={qty} sl={sl} tp={tp}"), c);
            }
            else if (action == "SELL")
            {
                EnterShort(qty, signal);
                SendAckOverWs(cmdId, "SENT", AppendLatency(c, $"SELL qty={qty} sl={sl} tp={tp}"), c);
            }
            else
            {
                SendAckOverWs(cmdId, "ERROR", AppendLatency(c, "unknown action"), c);
            }
        }

        private void SendAckOverWs(string id, string status, string message = null, Cmd cmd = null)
        {
            if (string.IsNullOrWhiteSpace(id)) return;

            var ts = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture);
            long seq = Interlocked.Increment(ref _barSeq);
            var json = MiniJson.BuildAckV2(BotId, seq, id, status, message ?? "", ts, cmd);
            EnqueueHigh(json);
        }

        private DateTime ToUtcBarTime(int bip, DateTime barTime)
        {
            try
            {
                if (barTime.Kind == DateTimeKind.Utc) return barTime;
                if (barTime.Kind == DateTimeKind.Local) return barTime.ToUniversalTime();

                TimeZoneInfo tz = null;
                try { tz = BarsArray[bip].TradingHours.TimeZoneInfo; } catch { tz = null; }
                if (tz != null)
                    return TimeZoneInfo.ConvertTimeToUtc(barTime, tz);
            }
            catch { }

            try { return DateTime.SpecifyKind(barTime, DateTimeKind.Local).ToUniversalTime(); } catch { }
            return DateTime.UtcNow;
        }

        private string TimeframeTag(int bip)
        {
            if (!string.IsNullOrWhiteSpace(ForceTimeframeText))
                return ForceTimeframeText.Trim();

            try
            {
                var p = BarsArray[bip].BarsPeriod;
                if (p.BarsPeriodType == BarsPeriodType.Second) return p.Value.ToString(CultureInfo.InvariantCulture) + "s";
                if (p.BarsPeriodType == BarsPeriodType.Minute) return p.Value.ToString(CultureInfo.InvariantCulture) + "m";
                if (p.BarsPeriodType == BarsPeriodType.Day) return p.Value.ToString(CultureInfo.InvariantCulture) + "d";
            }
            catch { }

            return "1m";
        }

        private void SendBarOverWs(int barsInProgress, int barsAgo)
        {
            string sym = !string.IsNullOrWhiteSpace(ForceSymbol) ? ForceSymbol.Trim() : NormalizeSymbol();
            string timeframe = TimeframeTag(barsInProgress);

            DateTime raw = Times[barsInProgress][barsAgo];
            string barTsUtc = ToUtcBarTime(barsInProgress, raw).ToString("o", CultureInfo.InvariantCulture);

            long vol = 0L;
            try { vol = Math.Max(0L, (long)Volumes[barsInProgress][barsAgo]); } catch { vol = 0L; }

            string sendTsUtc = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture);
            long seq = Interlocked.Increment(ref _barSeq);

            var json = MiniJson.BuildBarDataV2(
                BotId,
                seq,
                sendTsUtc,
                barTsUtc,
                sym,
                timeframe,
                Opens[barsInProgress][barsAgo],
                Highs[barsInProgress][barsAgo],
                Lows[barsInProgress][barsAgo],
                Closes[barsInProgress][barsAgo],
                vol,
                CurrentMode(),
                EnableLiveExecution,
                IsInStrategyAnalyzer,
                barsInProgress
            );

            _lastBarSentUtc = DateTime.UtcNow;
            Interlocked.Increment(ref _barSendCount);
            EnqueueLow(json);

            if (EnableLogging)
            {
                long n = Interlocked.Increment(ref _barSeq);
                if (n % 60 == 0)
                    Print($"Bar sent OK via WS: {sym} {timeframe} c={Closes[barsInProgress][barsAgo]:F2} dropLo={_outDropLo}");
            }
        }

        private void LogVolumeSnapshot(int barsInProgress)
        {
            if (!EnableLogging || !EnableVolumeDiagnostics) return;

            int vol = (int)Volumes[barsInProgress][0];
            if (vol != _lastVolumeValue)
            {
                _lastVolumeValue = vol;
                Print($"Volume snapshot: {vol} | symbol={NormalizeSymbol()} | tf={NormalizeTimeframe(barsInProgress)}");
            }

            if (vol <= 1)
            {
                long n = Interlocked.Increment(ref _volumeWarnSeq);
                if (n % 60 == 0)
                    Print("Volume appears fixed at 1. Check market data feed/instrument subscription.");
            }
        }

        private string AppendLatency(Cmd c, string message)
        {
            if (c == null || c.ReceivedAtUtc == default(DateTime))
            {
                return message;
            }

            var ms = (DateTime.UtcNow - c.ReceivedAtUtc).TotalMilliseconds;
            return $"{message} | latencyMs={ms:0}";
        }
        
        private void EnqueueHigh(string json)
        {
            if (string.IsNullOrWhiteSpace(json)) return;
            if (Interlocked.Increment(ref _outHiDepth) > MAX_OUT_HI)
            {
                Interlocked.Decrement(ref _outHiDepth);
                return;
            }
            _outHi.Enqueue(json);
            _outSignal.Release();
        }

        private void EnqueueLow(string json)
        {
            if (string.IsNullOrWhiteSpace(json)) return;

            // If disconnected, drop low-priority bars immediately (anti-hang).
            if (_ws == null || _ws.State != WebSocketState.Open)
            {
                Interlocked.Increment(ref _outDropLo);
                return;
            }

            if (Interlocked.Increment(ref _outLoDepth) > MAX_OUT_LO)
            {
                Interlocked.Decrement(ref _outLoDepth);
                Interlocked.Increment(ref _outDropLo);
                return;
            }
            _outLo.Enqueue(json);
            _outSignal.Release();
        }

        private async Task SendLoop(ClientWebSocket ws, CancellationToken ct)
        {
            while (!ct.IsCancellationRequested && ws != null)
            {
                try
                {
                    await _outSignal.WaitAsync(SEND_LOOP_IDLE_MS, ct).ConfigureAwait(false);

                    if (ct.IsCancellationRequested) break;
                    if (!ReferenceEquals(ws, _ws)) break;
                    if (ws.State != WebSocketState.Open) continue;

                    if (_outHi.TryDequeue(out var hi))
                    {
                        Interlocked.Decrement(ref _outHiDepth);
                        await SendText(ws, hi, ct).ConfigureAwait(false);
                        continue;
                    }

                    if (_outLo.TryDequeue(out var lo))
                    {
                        Interlocked.Decrement(ref _outLoDepth);
                        await SendText(ws, lo, ct).ConfigureAwait(false);
                        continue;
                    }
                }
                catch (TaskCanceledException) { break; }
                catch
                {
                    try { await Task.Delay(100, ct).ConfigureAwait(false); } catch { }
                }
            }
        }

        private async Task SendText(ClientWebSocket ws, string json, CancellationToken ct)
        {
            try
            {
                if (ws == null || ws.State != WebSocketState.Open) return;
                var bytes = Encoding.UTF8.GetBytes(json);
                await ws.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, ct).ConfigureAwait(false);
                _lastWsSendUtc = DateTime.UtcNow;
            }
            catch { }
        }

        private string NormalizeSymbol()
        {
            try
            {
                if (Instrument != null && Instrument.MasterInstrument != null)
                    return Instrument.MasterInstrument.Name;

                if (Instrument != null && !string.IsNullOrWhiteSpace(Instrument.FullName))
                {
                    var m = Regex.Match(Instrument.FullName, @"^[A-Za-z]+");
                    if (m.Success) return m.Value;
                    return Instrument.FullName;
                }
            }
            catch { }
            return "MNQ";
        }

        private string NormalizeTimeframe()
        {
            try
            {
                return NormalizeTimeframe(0);
            }
            catch { }
            return "1 Minute";
        }

        private string NormalizeTimeframe(int barsInProgress)
        {
            try
            {
                if (BarsArray == null || barsInProgress < 0 || barsInProgress >= BarsArray.Length)
                    return "1 Minute";

                var period = BarsArray[barsInProgress].BarsPeriod;
                if (period == null) return "1 Minute";

                if (period.BarsPeriodType == BarsPeriodType.Minute)
                {
                    int v = period.Value;
                    return v == 1 ? "1 Minute" : v.ToString(CultureInfo.InvariantCulture) + " Minute";
                }
                if (period.BarsPeriodType == BarsPeriodType.Second)
                {
                    int v = period.Value;
                    return v == 1 ? "1 Second" : v.ToString(CultureInfo.InvariantCulture) + " Second";
                }
                if (period.BarsPeriodType == BarsPeriodType.Day)
                    return "1 Day";
            }
            catch { }
            return "1 Minute";
        }
        
        private Uri GetWsUrl()
        {
            string url = ServerUrl.Trim();
            if (url.StartsWith("http"))
            {
                url = Regex.Replace(url, "^http", "ws");
            }
            if (!url.StartsWith("ws://") && !url.StartsWith("wss://"))
            {
                url = "ws://" + url;
            }
            if (url.EndsWith("/")) url = url.TrimEnd('/');
            
            return new Uri($"{url}/ws/{Uri.EscapeDataString(BotId)}");
        }

        private Cmd ParseCommand(string json)
        {
            if (string.IsNullOrWhiteSpace(json)) return null;

            try
            {
                var action = MiniJson.GetString(json, "action");
                if (string.IsNullOrWhiteSpace(action))
                {
                    var payloadMatch = Regex.Match(
                        json,
                        "\"payload\"\\s*:\\s*\\{(?<p>.*)\\}\\s*\\}?\\s*$",
                        RegexOptions.CultureInvariant | RegexOptions.Singleline);
                    if (payloadMatch.Success)
                    {
                        var payload = "{" + payloadMatch.Groups["p"].Value + "}";
                        json = payload;
                        action = MiniJson.GetString(json, "action");
                    }
                }

                return new Cmd
                {
                    Id = MiniJson.GetString(json, "id"),
                    Action = action,
                    Qty = MiniJson.GetInt(json, "qty", 0),
                    SlTicks = MiniJson.GetInt(json, "slTicks", 0),
                    TpTicks = MiniJson.GetInt(json, "tpTicks", 0),
                    Tag = MiniJson.GetString(json, "tag"),
                    Symbol = MiniJson.GetString(json, "symbol"),
                    ReceivedAtUtc = DateTime.UtcNow
                };
            }
            catch (Exception ex)
            {
                if (EnableLogging) Print("ParseCommand error: " + ex.Message);
                return null;
            }
        }

        [NinjaScriptProperty]
        [Display(Name = "Server URL (host:port)", Order = 1, GroupName = "Connection")]
        public string ServerUrl { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "BotId", Order = 2, GroupName = "Connection")]
        public string BotId { get; set; }
        
        [NinjaScriptProperty]
        [Display(Name = "API Key", Order = 3, GroupName = "Connection")]
        public string ApiKey { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Enable Receive Commands", Order = 1, GroupName = "Bridge")]
        public bool EnableReceiveCommands { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Enable Send Bars", Order = 2, GroupName = "Bridge")]
        public bool EnableSendBars { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Send Bars In Backtest", Order = 3, GroupName = "Bridge")]
        public bool SendBarsInBacktest { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Enable LIVE Execution", Order = 4, GroupName = "Bridge")]
        public bool EnableLiveExecution { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Send Only Closed Bars", Order = 5, GroupName = "Bridge")]
        public bool SendOnlyClosedBars { get; set; }

        [NinjaScriptProperty]
        [Range(1, 200)]
        [Display(Name = "Default Qty", Order = 1, GroupName = "Risk")]
        public int DefaultQty { get; set; }

        [NinjaScriptProperty]
        [Range(1, 500)]
        [Display(Name = "Max Contracts", Order = 2, GroupName = "Risk")]
        public int MaxContracts { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Allow Reversal", Order = 3, GroupName = "Risk")]
        public bool AllowReversal { get; set; }

        [NinjaScriptProperty]
        [Range(0, 500)]
        [Display(Name = "Default StopLoss (ticks)", Order = 4, GroupName = "Risk")]
        public int DefaultStopLossTicks { get; set; }

        [NinjaScriptProperty]
        [Range(0, 500)]
        [Display(Name = "Default TakeProfit (ticks)", Order = 5, GroupName = "Risk")]
        public int DefaultTakeProfitTicks { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Force Timeframe Text", Order = 10, GroupName = "Normalize")]
        public string ForceTimeframeText { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Force Symbol", Order = 11, GroupName = "Normalize")]
        public string ForceSymbol { get; set; }

        [NinjaScriptProperty]
        [Range(1, 60)]
        [Display(Name = "Live Bar Seconds", Order = 12, GroupName = "Normalize")]
        public int LiveBarSeconds { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Enable Logging", Order = 99, GroupName = "Debug")]
        public bool EnableLogging { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Enable Volume Diagnostics", Order = 100, GroupName = "Debug")]
        public bool EnableVolumeDiagnostics { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Enable Monitor", Order = 101, GroupName = "Debug")]
        public bool EnableMonitor { get; set; }

        [NinjaScriptProperty]
        [Range(1, 60)]
        [Display(Name = "Monitor Interval (sec)", Order = 102, GroupName = "Debug")]
        public int MonitorIntervalSec { get; set; }

        private const string FileMarker = "hola mundo";
    }
}
// hola mundo

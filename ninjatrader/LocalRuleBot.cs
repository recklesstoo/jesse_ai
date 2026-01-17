#region Using declarations
using System;
#endregion

namespace NinjaTrader.NinjaScript.Strategies.WyckoffBot
{
    // Baseline deterministic bot: no dependencies, stable decisions for testing.
    // Policy (simple):
    // - If close > open and confidence ok -> BUY
    // - If close < open -> SELL
    // - Else HOLD
    public sealed class LocalRuleBot : IBotDecisionEngine
    {
        public string Name => "LocalRuleBot";

        public double MinAtrTicks { get; set; } = 2.0;
        public int DefaultQty { get; set; } = 1;
        public int DefaultSlTicks { get; set; } = 10;
        public int DefaultTpTicks { get; set; } = 12;

        private readonly double _tickSize;

        public LocalRuleBot(double tickSize)
        {
            _tickSize = tickSize <= 0 ? 0.25 : tickSize;
        }

        public Decision GetDecision(BarContext ctx)
        {
            if (ctx == null) return Decision.Hold("ctx=null");
            if (ctx.Atr14 <= 0) return Decision.Hold("atr=0");
            double atrTicks = ctx.Atr14 / _tickSize;
            if (atrTicks < MinAtrTicks) return Decision.Hold("atr_too_low");

            if (ctx.Close > ctx.Open)
            {
                return new Decision
                {
                    Action = DecisionAction.BUY,
                    Confidence = 0.55,
                    Qty = DefaultQty,
                    SlTicks = DefaultSlTicks,
                    TpTicks = DefaultTpTicks,
                    Reason = "close>open",
                    BotName = Name
                };
            }
            if (ctx.Close < ctx.Open)
            {
                return new Decision
                {
                    Action = DecisionAction.SELL,
                    Confidence = 0.55,
                    Qty = DefaultQty,
                    SlTicks = DefaultSlTicks,
                    TpTicks = DefaultTpTicks,
                    Reason = "close<open",
                    BotName = Name
                };
            }
            return Decision.Hold("doji");
        }
    }
}


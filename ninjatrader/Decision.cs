#region Using declarations
using System;
#endregion

namespace NinjaTrader.NinjaScript.Strategies.WyckoffBot
{
    public enum DecisionAction
    {
        HOLD = 0,
        BUY = 1,
        SELL = 2,
        FLATTEN = 3
    }

    public sealed class Decision
    {
        public DecisionAction Action { get; set; } = DecisionAction.HOLD;
        public double Confidence { get; set; } = 0.0; // 0..1
        public int Qty { get; set; } = 0;
        public int SlTicks { get; set; } = 0;
        public int TpTicks { get; set; } = 0;
        public string Reason { get; set; } = "";
        public string BotName { get; set; } = "";

        public static Decision Hold(string reason = "")
        {
            return new Decision { Action = DecisionAction.HOLD, Confidence = 0.0, Qty = 0, Reason = reason ?? "" };
        }
    }
}


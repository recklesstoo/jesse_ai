#region Using declarations
using System;
#endregion

namespace NinjaTrader.NinjaScript.Strategies.WyckoffBot
{
    public sealed class BarContext
    {
        public string BotId { get; set; }
        public string Symbol { get; set; }
        public string Timeframe { get; set; }
        public DateTime BarTimeUtc { get; set; }

        public double Open { get; set; }
        public double High { get; set; }
        public double Low { get; set; }
        public double Close { get; set; }
        public long Volume { get; set; }

        // Minimal features
        public double TrueRange { get; set; }
        public double Atr14 { get; set; }

        // Session markers
        public bool IsFirstBarOfSession { get; set; }
        public int BarsSinceSessionStart { get; set; }

        // Position snapshot
        public string MarketPosition { get; set; } // Flat/Long/Short
        public int PositionQty { get; set; }
    }
}


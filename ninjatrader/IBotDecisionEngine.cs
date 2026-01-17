#region Using declarations
using System;
#endregion

namespace NinjaTrader.NinjaScript.Strategies.WyckoffBot
{
    public interface IBotDecisionEngine
    {
        Decision GetDecision(BarContext ctx);
        string Name { get; }
    }
}


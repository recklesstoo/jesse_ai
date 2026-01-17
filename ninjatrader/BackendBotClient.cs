#region Using declarations
using System;
using System.Collections.Concurrent;
using System.Globalization;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
#endregion

namespace NinjaTrader.NinjaScript.Strategies.WyckoffBot
{
    // Optional backend client: one request per CLOSED bar.
    // Non-blocking: if backend slow/unavailable -> HOLD.
    public sealed class BackendBotClient : IBotDecisionEngine
    {
        public string Name => "BackendBotClient";

        public string ApiBase { get; set; } = "http://127.0.0.1:8000";
        public int TimeoutMs { get; set; } = 350;

        private readonly ConcurrentQueue<BarContext> _q = new ConcurrentQueue<BarContext>();
        private volatile Decision _last = Decision.Hold("backend:not_ready");
        private int _workerStarted = 0;
        private CancellationTokenSource _cts;

        public void Start()
        {
            if (Interlocked.Exchange(ref _workerStarted, 1) == 1) return;
            _cts = new CancellationTokenSource();
            Task.Run(() => Worker(_cts.Token));
        }

        public void Stop()
        {
            try { _cts?.Cancel(); } catch { }
        }

        public Decision GetDecision(BarContext ctx)
        {
            if (ctx == null) return Decision.Hold("ctx=null");
            // enqueue and return last known decision (or HOLD)
            _q.Enqueue(ctx);
            return _last ?? Decision.Hold("backend:last_null");
        }

        private async Task Worker(CancellationToken ct)
        {
            using (var http = new HttpClient())
            {
                while (!ct.IsCancellationRequested)
                {
                    try
                    {
                        if (!_q.TryDequeue(out var ctx))
                        {
                            await Task.Delay(10, ct).ConfigureAwait(false);
                            continue;
                        }

                        var payload = BuildJson(ctx);
                        var req = new HttpRequestMessage(HttpMethod.Post, ApiBase.TrimEnd('/') + "/api/v1/backtest/decision");
                        req.Content = new StringContent(payload, Encoding.UTF8, "application/json");

                        using (var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(ct))
                        {
                            timeoutCts.CancelAfter(Math.Max(50, TimeoutMs));
                            var resp = await http.SendAsync(req, timeoutCts.Token).ConfigureAwait(false);
                            var body = await resp.Content.ReadAsStringAsync().ConfigureAwait(false);
                            if (!resp.IsSuccessStatusCode)
                            {
                                _last = Decision.Hold("backend:http_" + ((int)resp.StatusCode).ToString(CultureInfo.InvariantCulture));
                                continue;
                            }
                            var d = TryParseDecision(body);
                            _last = d ?? Decision.Hold("backend:parse_fail");
                        }
                    }
                    catch (OperationCanceledException)
                    {
                        // ignore
                    }
                    catch
                    {
                        _last = Decision.Hold("backend:error");
                        try { await Task.Delay(50, ct).ConfigureAwait(false); } catch { }
                    }
                }
            }
        }

        private static string JsonStr(string s)
        {
            if (s == null) s = "";
            return s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n");
        }

        private static string BuildJson(BarContext ctx)
        {
            // minimal JSON (no external deps)
            var sb = new StringBuilder();
            sb.Append("{");
            sb.Append("\"botId\":\"").Append(JsonStr(ctx.BotId ?? "")).Append("\",");
            sb.Append("\"symbol\":\"").Append(JsonStr(ctx.Symbol ?? "")).Append("\",");
            sb.Append("\"timeframe\":\"").Append(JsonStr(ctx.Timeframe ?? "")).Append("\",");
            sb.Append("\"bar\":{");
            sb.Append("\"ts\":\"").Append(JsonStr(ctx.BarTimeUtc.ToString("o", CultureInfo.InvariantCulture))).Append("\",");
            sb.Append("\"o\":").Append(ctx.Open.ToString("R", CultureInfo.InvariantCulture)).Append(",");
            sb.Append("\"h\":").Append(ctx.High.ToString("R", CultureInfo.InvariantCulture)).Append(",");
            sb.Append("\"l\":").Append(ctx.Low.ToString("R", CultureInfo.InvariantCulture)).Append(",");
            sb.Append("\"c\":").Append(ctx.Close.ToString("R", CultureInfo.InvariantCulture)).Append(",");
            sb.Append("\"v\":").Append(ctx.Volume.ToString(CultureInfo.InvariantCulture));
            sb.Append("},");
            sb.Append("\"position_state\":{");
            sb.Append("\"marketPosition\":\"").Append(JsonStr(ctx.MarketPosition ?? "")).Append("\",");
            sb.Append("\"qty\":").Append(ctx.PositionQty.ToString(CultureInfo.InvariantCulture));
            sb.Append("}");
            sb.Append("}");
            return sb.ToString();
        }

        private static Decision TryParseDecision(string json)
        {
            if (string.IsNullOrWhiteSpace(json)) return null;
            string action = ExtractString(json, "action");
            string reason = ExtractString(json, "reason");
            string botName = ExtractString(json, "botName");
            int qty = ExtractInt(json, "qty");
            int sl = ExtractInt(json, "slTicks");
            int tp = ExtractInt(json, "tpTicks");
            double conf = ExtractDouble(json, "confidence");

            DecisionAction a = DecisionAction.HOLD;
            if (!string.IsNullOrWhiteSpace(action))
            {
                var up = action.Trim().ToUpperInvariant();
                if (up == "BUY") a = DecisionAction.BUY;
                else if (up == "SELL") a = DecisionAction.SELL;
                else if (up == "FLATTEN") a = DecisionAction.FLATTEN;
            }

            return new Decision
            {
                Action = a,
                Confidence = conf,
                Qty = qty,
                SlTicks = sl,
                TpTicks = tp,
                Reason = reason ?? "",
                BotName = botName ?? "Backend"
            };
        }

        private static string ExtractString(string json, string key)
        {
            var m = Regex.Match(json, "\"" + Regex.Escape(key) + "\"\\s*:\\s*\"(?<v>(?:\\\\.|[^\"\\\\])*)\"", RegexOptions.CultureInvariant);
            if (!m.Success) return null;
            return m.Groups["v"].Value.Replace("\\\"", "\"").Replace("\\\\", "\\");
        }

        private static int ExtractInt(string json, string key)
        {
            var m = Regex.Match(json, "\"" + Regex.Escape(key) + "\"\\s*:\\s*(?<v>-?\\d+)", RegexOptions.CultureInvariant);
            if (!m.Success) return 0;
            int v;
            return int.TryParse(m.Groups["v"].Value, NumberStyles.Integer, CultureInfo.InvariantCulture, out v) ? v : 0;
        }

        private static double ExtractDouble(string json, string key)
        {
            var m = Regex.Match(json, "\"" + Regex.Escape(key) + "\"\\s*:\\s*(?<v>-?\\d+(?:\\.\\d+)?)", RegexOptions.CultureInvariant);
            if (!m.Success) return 0.0;
            double v;
            return double.TryParse(m.Groups["v"].Value, NumberStyles.Float, CultureInfo.InvariantCulture, out v) ? v : 0.0;
        }
    }
}


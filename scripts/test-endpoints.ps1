$base = 'http://localhost:8000'
$bot = 'bot-1'
$results = @()

function Test-Get($path) {
  $url = "$base$path"
  try {
    Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 5 | Out-Null
    $script:results += [pscustomobject]@{ Method = 'GET'; Path = $path; Ok = $true; Note = 'ok' }
  } catch {
    $script:results += [pscustomobject]@{ Method = 'GET'; Path = $path; Ok = $false; Note = $_.Exception.Message }
  }
}

function Test-Post($path, $body) {
  $url = "$base$path"
  try {
    $json = $body | ConvertTo-Json -Depth 6
    Invoke-RestMethod -Uri $url -Method Post -ContentType 'application/json' -Body $json -TimeoutSec 5 | Out-Null
    $script:results += [pscustomobject]@{ Method = 'POST'; Path = $path; Ok = $true; Note = 'ok' }
  } catch {
    $script:results += [pscustomobject]@{ Method = 'POST'; Path = $path; Ok = $false; Note = $_.Exception.Message }
  }
}

function Test-Form($path, $body) {
  $url = "$base$path"
  try {
    Invoke-RestMethod -Uri $url -Method Post -ContentType 'application/x-www-form-urlencoded' -Body $body -TimeoutSec 5 | Out-Null
    $script:results += [pscustomobject]@{ Method = 'POST'; Path = $path; Ok = $true; Note = 'ok' }
  } catch {
    $script:results += [pscustomobject]@{ Method = 'POST'; Path = $path; Ok = $false; Note = $_.Exception.Message }
  }
}

function Test-WebSocket($wsUrl) {
  $client = [System.Net.WebSockets.ClientWebSocket]::new()
  $cts = [System.Threading.CancellationTokenSource]::new()
  $cts.CancelAfter(3000)
  $recvBuffer = New-Object byte[] 2048

  try {
    $client.ConnectAsync([Uri]$wsUrl, $cts.Token).Wait()
    if ($client.State -ne [System.Net.WebSockets.WebSocketState]::Open) {
      return "$wsUrl -> not open"
    }

    $segment = New-Object System.ArraySegment[byte] -ArgumentList (, $recvBuffer)
    $result = $client.ReceiveAsync($segment, $cts.Token).Result
    $payload = [System.Text.Encoding]::UTF8.GetString($recvBuffer, 0, $result.Count)
    return "$wsUrl -> received"
  } catch {
    return "$wsUrl -> error: $($_.Exception.Message)"
  } finally {
    if ($client.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
      $client.CloseAsync([System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure, 'done', [System.Threading.CancellationToken]::None).Wait()
    }
    $client.Dispose()
  }
}

# Health + metrics
Test-Get "/api/health"
Test-Get "/api/v1/health"
Test-Get "/api/metrics"
Test-Get "/api/v1/metrics?botId=$bot"
Test-Get "/api/bots"
Test-Get "/api/v1/bots"

# Logs + state
Test-Get "/api/commands/$bot/log?limit=5"
Test-Get "/api/v1/commands/$bot/log?limit=5"
Test-Get "/api/strategy/state?botId=$bot"
Test-Get "/api/v1/strategy/state?botId=$bot"
Test-Get "/api/strategy/parameters?botId=$bot"
Test-Get "/api/v1/strategy/parameters?botId=$bot"

# Config + AI
Test-Get "/api/wyckoff/config?botId=$bot"
Test-Get "/api/v1/wyckoff/config?botId=$bot"
Test-Get "/api/ai/auto-config?botId=$bot"
Test-Get "/api/v1/ai/auto-config?botId=$bot"
Test-Get "/api/ai-signals?botId=$bot"
Test-Get "/api/v1/ai-signals?botId=$bot"
Test-Get "/api/ai-signals/$bot/history?limit=1"
Test-Get "/api/v1/ai-signals/$bot/history?limit=1"

# Prices + news
Test-Get "/api/dynamic-prices?botId=$bot"
Test-Get "/api/v1/dynamic-prices?botId=$bot"
Test-Get "/api/news/status"
Test-Get "/api/v1/news/status"
Test-Get "/api/news/upcoming"
Test-Get "/api/v1/news/upcoming"

# Commands
Test-Post "/api/control/action" @{ botId = $bot; action = 'KILL'; reason = 'test' }
Test-Post "/api/v1/control/action" @{ botId = $bot; action = 'KILL'; reason = 'test' }
Test-Post "/api/toggle-mode" @{ botId = $bot; mode = 'LIVE' }
Test-Post "/api/v1/toggle-mode" @{ botId = $bot; mode = 'LIVE' }
Test-Post "/api/strategy/parameters" @{ botId = $bot; parameters = @{ foo = 'bar' } }
Test-Post "/api/v1/strategy/parameters" @{ botId = $bot; parameters = @{ foo = 'bar' } }
Test-Post "/api/wyckoff/config" @{ botId = $bot; break_pct = 0.0021 }
Test-Post "/api/v1/wyckoff/config" @{ botId = $bot; break_pct = 0.0021 }
Test-Post "/api/ai/auto-config" @{ botId = $bot; enabled = $false }
Test-Post "/api/v1/ai/auto-config" @{ botId = $bot; enabled = $false }
Test-Post "/api/bots/instrument" @{ botId = $bot; instrument = 'MNQ' }
Test-Post "/api/v1/bots/instrument" @{ botId = $bot; instrument = 'MNQ' }
Test-Post "/api/commands/$bot" @{ action = 'NONE'; qty = 0; slTicks = 0; tpTicks = 0; tag = 'test'; symbol = 'MNQ' }
Test-Post "/api/v1/commands/$bot" @{ action = 'NONE'; qty = 0; slTicks = 0; tpTicks = 0; tag = 'test'; symbol = 'MNQ' }
Test-Post "/api/commands/$bot/ack" @{ id = 'cmd_test'; status = 'OK'; message = 'test' }
Test-Post "/api/v1/commands/$bot/ack" @{ id = 'cmd_test'; status = 'OK'; message = 'test' }
Test-Post "/api/ai-order" @{ botId = $bot; action = 'BUY'; qty = 1; slTicks = 0; tpTicks = 0; tag = 'ai'; symbol = 'MNQ'; confidence = 0.9; signal = 'SOS' }
Test-Post "/api/v1/ai-order" @{ botId = $bot; action = 'BUY'; qty = 1; slTicks = 0; tpTicks = 0; tag = 'ai'; symbol = 'MNQ'; confidence = 0.9; signal = 'SOS' }
Test-Post "/api/manual-order-advanced" @{ botId = $bot; action = 'BUY'; qty = 1; slTicks = 0; tpTicks = 0; tag = 'manual'; symbol = 'MNQ' }
Test-Post "/api/v1/manual-order-advanced" @{ botId = $bot; action = 'BUY'; qty = 1; slTicks = 0; tpTicks = 0; tag = 'manual'; symbol = 'MNQ' }
Test-Post "/api/configure-prices" @{ botId = $bot; instrument = 'MNQ'; prices = @{ bid = 1; ask = 2 } }
Test-Post "/api/v1/configure-prices" @{ botId = $bot; instrument = 'MNQ'; prices = @{ bid = 1; ask = 2 } }

$event = @{ title = 'CPI'; ts = (Get-Date).ToUniversalTime().AddHours(1).ToString('o'); impact = 'high'; notes = 'test'; symbol = 'MNQ' }
Test-Post "/api/news/add_event" $event
Test-Post "/api/v1/news/add_event" $event

# Bars
$bar = @{ ts = (Get-Date).ToUniversalTime().ToString('o'); symbol = 'MNQ'; timeframe = '1 Minute'; o = 1; h = 2; l = 0.5; c = 1.5; v = 1000 }
$batch = @{ botId = $bot; mode = 'LIVE'; account = 'sim'; instrument = 'MNQ'; bars = @($bar) }
Test-Post "/api/bars/batch" $batch
Test-Post "/api/v1/bars/batch" $batch

$formBody = @{ botId = $bot; mode = 'LIVE'; timestamp = (Get-Date).ToUniversalTime().ToString('o'); symbol = 'MNQ'; timeframe = '1 Minute'; open = '1'; high = '2'; low = '0.5'; close = '1.5'; volume = '1000' }
Test-Form "/api/bar-data" $formBody

# WebSockets
$wsLive = Test-WebSocket 'ws://localhost:8000/ws/live'
$wsBot = Test-WebSocket "ws://localhost:8000/ws/$bot"

$results | Format-Table -AutoSize | Out-String -Width 200 | Write-Output
$wsLive | Write-Output
$wsBot | Write-Output

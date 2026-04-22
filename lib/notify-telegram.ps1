# Telegram notification backend for Windows. Dot-sourced by notify.ps1.
# Requires env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

function Get-TgApi { return "https://api.telegram.org/bot$env:TELEGRAM_BOT_TOKEN" }

# Send a pitch message with inline keyboard. Returns message_id.
function _Tg-SendPitch {
    param([string]$Message, [string]$KeyboardJson)
    $api  = Get-TgApi
    $body = @{
        chat_id      = $env:TELEGRAM_CHAT_ID
        text         = $Message
        parse_mode   = "HTML"
        reply_markup = @{ inline_keyboard = ($KeyboardJson | ConvertFrom-Json) }
    } | ConvertTo-Json -Depth 10 -Compress

    $resp = Invoke-RestMethod -Uri "$api/sendMessage" -Method Post `
              -ContentType "application/json" -Body $body
    return $resp.result.message_id
}

# Poll for callback query on a specific message_id.
# Returns "approved", "rejected", or "pending".
function _Tg-PollReply {
    param([long]$MessageId)
    $api  = Get-TgApi
    try {
        $resp = Invoke-RestMethod -Uri "$api/getUpdates?allowed_updates=callback_query&limit=100"
    } catch {
        return "pending"
    }

    foreach ($update in $resp.result) {
        $cq = $update.callback_query
        if (-not $cq) { continue }
        if ($cq.message.message_id -eq $MessageId) {
            # Acknowledge to dismiss loading indicator
            try {
                Invoke-RestMethod -Uri "$api/answerCallbackQuery" -Method Post `
                    -ContentType "application/json" `
                    -Body (@{ callback_query_id = $cq.id } | ConvertTo-Json) | Out-Null
            } catch {}
            return if ($cq.data -eq "approve") { "approved" } else { "rejected" }
        }
    }
    return "pending"
}

# Send a plain text message.
function _Tg-SendText {
    param([string]$Message)
    $api  = Get-TgApi
    $body = @{
        chat_id    = $env:TELEGRAM_CHAT_ID
        text       = $Message
        parse_mode = "HTML"
    } | ConvertTo-Json -Compress
    try {
        Invoke-RestMethod -Uri "$api/sendMessage" -Method Post `
            -ContentType "application/json" -Body $body | Out-Null
    } catch {}
}

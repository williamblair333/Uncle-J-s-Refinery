# Notification dispatcher for Windows. Dot-source this in alert scripts.
# Reads NOTIFY_CHANNEL env var (default: telegram).

$_NotifyLibDir = $PSScriptRoot

function Invoke-NotifySendPitch {
    param([string]$Message, [string]$KeyboardJson)
    switch ($env:NOTIFY_CHANNEL ?? "telegram") {
        "telegram" {
            . "$_NotifyLibDir\notify-telegram.ps1"
            return _Tg-SendPitch -Message $Message -KeyboardJson $KeyboardJson
        }
        default { Write-Error "[notify] Unknown NOTIFY_CHANNEL: $env:NOTIFY_CHANNEL"; return $null }
    }
}

function Invoke-NotifyPollReply {
    param([long]$MessageId)
    switch ($env:NOTIFY_CHANNEL ?? "telegram") {
        "telegram" {
            . "$_NotifyLibDir\notify-telegram.ps1"
            return _Tg-PollReply -MessageId $MessageId
        }
        default { Write-Error "[notify] Unknown NOTIFY_CHANNEL: $env:NOTIFY_CHANNEL"; return "pending" }
    }
}

function Invoke-NotifySendText {
    param([string]$Message)
    switch ($env:NOTIFY_CHANNEL ?? "telegram") {
        "telegram" {
            . "$_NotifyLibDir\notify-telegram.ps1"
            _Tg-SendText -Message $Message
        }
        default { Write-Error "[notify] Unknown NOTIFY_CHANNEL: $env:NOTIFY_CHANNEL" }
    }
}

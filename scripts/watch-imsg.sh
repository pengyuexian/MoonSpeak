#!/bin/bash
# watch-imsg.sh
# 监听 iMessage 群的新音频，自动跑评测，完成后通知
# 用法: tmux new -s imsg-watch ./scripts/watch-imsg.sh

set -euo pipefail

# 加载环境变量
cd "$(dirname "$0")/.."
set -a
source .env
set +a

CHAT_ID="${IMSG_CHAT_ID:-}"
SENDER="${IMSG_SENDER:-}"
PROCESSED_FILE="${PROCESSED_FILE:-/tmp/imsg_watch_last_id}"
TELEGRAM_TARGET="${TELEGRAM_TARGET:-}"
IMSG_SUCCESS_TEXT="${IMSG_SUCCESS_TEXT:-你的打卡已批改完成，查看报告：__REPORT_URL__}"
TELEGRAM_SUCCESS_TEXT="${TELEGRAM_SUCCESS_TEXT:-✅ 英语打卡批改完成
报告：__REPORT_URL__}"
TELEGRAM_FAILURE_TEXT="${TELEGRAM_FAILURE_TEXT:-❌ 英语打卡批改失败
类型：__ERROR_TYPE__
原因：__ERROR__}"
MOONSPEAK_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_FILE="/tmp/imsg-watch.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

require_env() {
    local name="$1"
    local value="$2"
    if [[ -z "$value" ]]; then
        log "Missing required env: $name"
        exit 1
    fi
}

render_template() {
    local template="$1"
    local report_url="${2:-}"
    local error_type="${3:-}"
    local error_message="${4:-}"
    printf '%s' "$template" \
        | sed "s|__REPORT_URL__|$report_url|g" \
        | sed "s|__ERROR_TYPE__|$error_type|g" \
        | sed "s|__ERROR__|$error_message|g"
}

send_telegram_notification() {
    local status="$1"
    local url="${2:-}"
    local error_type="${3:-}"
    local error_message="${4:-}"
    local message=""

    if [[ "$status" == "success" ]]; then
        message="$(render_template "$TELEGRAM_SUCCESS_TEXT" "$url" "" "")"
    else
        message="$(render_template "$TELEGRAM_FAILURE_TEXT" "" "$error_type" "$error_message")"
    fi

    openclaw message send -m "$message" --channel telegram --target "$TELEGRAM_TARGET" 2>/dev/null || true
}

send_imessage_success() {
    local url="$1"
    local message
    message="$(render_template "$IMSG_SUCCESS_TEXT" "$url" "" "")"
    imsg send --chat-id "$CHAT_ID" --text "$message" 2>/dev/null || true
}

# 处理单个音频
process_audio() {
    local msg_id="$1"
    local audio_path="$2"
    
    log "Processing audio: msg_id=$msg_id, path=$audio_path"
    
    # 复制到临时文件（避免原文件被移动）
    temp_file=$(mktemp /tmp/imsg_audio_XXXXXX.m4a)
    cp "$audio_path" "$temp_file"
    
    # 跑评测
    cd "$MOONSPEAK_DIR"
    source /opt/miniconda3/etc/profile.d/conda.sh
    conda activate moonspeak
    
    set +e
    result_json=$(conda run --no-capture-output -n moonspeak env PYTHONPATH=.:src python -m moonspeak.run_assessment "$temp_file" 2>>"$LOG_FILE")
    assessment_exit=$?
    set -e
    
    # 清理临时文件
    rm -f "$temp_file"

    report_url=$(python3 -c 'import json,sys; data=json.loads(sys.argv[1]); print(data.get("report_url", ""))' "$result_json")
    error_type=$(python3 -c 'import json,sys; data=json.loads(sys.argv[1]); print(data.get("error_type", ""))' "$result_json")
    error_message=$(python3 -c 'import json,sys; data=json.loads(sys.argv[1]); print(data.get("error", ""))' "$result_json")

    if [[ $assessment_exit -eq 0 ]] && [[ -n "$report_url" ]]; then
        log "Success: $report_url"
        send_telegram_notification "success" "$report_url" "" ""
        send_imessage_success "$report_url"
    else
        log "Failed: [$error_type] $error_message"
        send_telegram_notification "failure" "" "$error_type" "$error_message"
    fi
    
    # 更新状态
    echo "$msg_id" > "$PROCESSED_FILE"
}

# 获取上次处理到的最新 message ID
get_last_id() {
    if [[ -f "$PROCESSED_FILE" ]]; then
        cat "$PROCESSED_FILE"
    fi
}

# 主循环：用 imsg watch 监听
require_env "IMSG_CHAT_ID" "$CHAT_ID"
require_env "IMSG_SENDER" "$SENDER"
require_env "TELEGRAM_TARGET" "$TELEGRAM_TARGET"

log "Starting watch on chat_id=$CHAT_ID"

imsg watch --chat-id "$CHAT_ID" --attachments 2>/dev/null | while IFS= read -r line; do
    # 跳过空行
    [[ -z "$line" ]] && continue
    
    # 提取 id 和 sender
    msg_id=$(echo "$line" | grep -o '"id":[0-9]*' | head -1 | cut -d':' -f2)
    sender=$(echo "$line" | grep -o '"sender":"[^"]*"' | head -1 | cut -d'"' -f4)
    
    if [[ "$sender" == *"$SENDER"* ]]; then
        # 检查是否有音频附件
        if echo "$line" | grep -q '"mime_type":"audio/x-m4a"'; then
            audio_path=$(echo "$line" | grep -o '"original_path":"[^"]*"' | head -1 | cut -d'"' -f4)
            
            last_id=$(get_last_id)
            if [[ "$msg_id" != "$last_id" ]]; then
                log "New audio detected: msg_id=$msg_id"
                process_audio "$msg_id" "$audio_path"
            fi
        fi
    fi
done

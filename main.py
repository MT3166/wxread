# main.py 主逻辑：包括字段拼接、模拟请求
import os
import re
import json
import time
import random
import logging
import hashlib
import requests
import urllib.parse
from push import push
from config import data, headers, cookies, READ_NUM, PUSH_METHOD, book, chapter

# 配置日志格式
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)-8s - %(message)s')

# 加密盐及其它默认值
KEY = "3c5c8717f3daf09iop3423zafeqoi"
READ_URL = "https://weread.qq.com/web/book/read"
RENEW_URL = "https://weread.qq.com/web/login/renewal"
FIX_SYNCKEY_URL = "https://weread.qq.com/web/book/chapterInfos"


def _str_to_bool(value):
    """统一处理布尔配置字符串"""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "t", "yes"}


def _build_cookie_payload():
    """构造续签请求体，兼容 weread-bot 的配置方式"""
    env_flag = os.getenv("HACK_COOKIE_REFRESH_QL")
    if env_flag is not None:
        ql_flag = _str_to_bool(env_flag)
    else:
        ql_flag = _str_to_bool(cookies.get("wr_ql"))

    payload = {"rq": "%2Fweb%2Fbook%2Fread", "ql": ql_flag}
    logging.debug("🔧 续签 payload: %s", payload)
    return payload


def encode_data(data):
    """数据编码"""
    return '&'.join(f"{k}={urllib.parse.quote(str(data[k]), safe='')}" for k in sorted(data.keys()))


def cal_hash(input_string):
    """计算哈希值"""
    _7032f5 = 0x15051505
    _cc1055 = _7032f5
    length = len(input_string)
    _19094e = length - 1

    while _19094e > 0:
        _7032f5 = 0x7fffffff & (_7032f5 ^ ord(input_string[_19094e]) << (length - _19094e) % 30)
        _cc1055 = 0x7fffffff & (_cc1055 ^ ord(input_string[_19094e - 1]) << _19094e % 30)
        _19094e -= 2

    return hex(_7032f5 + _cc1055)[2:].lower()

def _refresh_cookie_once():
    """调用续签接口刷新 wr_skey，成功返回 True"""
    logging.info("🍪 刷新cookie...")
    payload = _build_cookie_payload()
    try:
        response = requests.post(
            RENEW_URL,
            headers=headers,
            cookies=cookies,
            json=payload,
            timeout=10,
        )
    except requests.RequestException as exc:
        logging.error("❌ Cookie刷新失败，请求异常：%s", exc)
        return False

    new_skey = response.cookies.get("wr_skey")

    if not new_skey:
        set_cookie = response.headers.get("Set-Cookie", "")
        for cookie in set_cookie.split(','):
            if "wr_skey" in cookie:
                parts = cookie.split(';')[0]
                if '=' in parts:
                    new_skey = parts.split('=', 1)[1].strip()
                    break

    if not new_skey:
        logging.error(
            "❌ Cookie刷新失败，未找到 wr_skey，status=%s, body=%s",
            response.status_code,
            response.text,
        )
        return False

    cookies['wr_skey'] = new_skey
    logging.info("✅ Cookie刷新成功，新密钥: %s***", new_skey[:8])
    return True

def fix_no_synckey():
    requests.post(FIX_SYNCKEY_URL, headers=headers, cookies=cookies,
                             data=json.dumps({"bookIds":["3300060341"]}, separators=(',', ':')))

def refresh_cookie():
    if _refresh_cookie_once():
        logging.info("🔄 重新本次阅读。")
        return

    ERROR_CODE = "❌ 无法获取新密钥或者WXREAD_CURL_BASH配置有误，终止运行。"
    logging.error(ERROR_CODE)
    try:
        push(ERROR_CODE, PUSH_METHOD)
    except Exception:
        logging.exception("❌ 推送通知失败，请检查 PUSH_METHOD 及其配置。")
        raise
    raise Exception(ERROR_CODE)

refresh_cookie()
index = 1
lastTime = int(time.time()) - 30
logging.info(f"⏱️ 一共需要阅读 {READ_NUM} 次...")

while index <= READ_NUM:
    data.pop('s')
    data['b'] = random.choice(book)
    data['c'] = random.choice(chapter)
    thisTime = int(time.time())
    data['ct'] = thisTime
    data['rt'] = thisTime - lastTime
    data['ts'] = int(thisTime * 1000) + random.randint(0, 1000)
    data['rn'] = random.randint(0, 1000)
    data['sg'] = hashlib.sha256(f"{data['ts']}{data['rn']}{KEY}".encode()).hexdigest()
    data['s'] = cal_hash(encode_data(data))

    logging.info(f"⏱️ 尝试第 {index} 次阅读...")
    logging.info(f"📕 data: {data}")
    response = requests.post(READ_URL, headers=headers, cookies=cookies, data=json.dumps(data, separators=(',', ':')))
    resData = response.json()
    logging.info(f"📕 response: {resData}")

    if 'succ' in resData:
        if 'synckey' in resData:
            lastTime = thisTime
            index += 1
            time.sleep(30)
            logging.info(f"✅ 阅读成功，阅读进度：{(index - 1) * 0.5} 分钟")
        else:
            logging.warning("❌ 无synckey, 尝试修复...")
            fix_no_synckey()
    else:
        logging.warning("❌ cookie 已过期，尝试刷新...")
        refresh_cookie()

logging.info("🎉 阅读脚本已完成！")

if PUSH_METHOD not in (None, ''):
    logging.info("⏱️ 开始推送...")
    push(f"🎉 微信读书自动阅读完成！\n⏱️ 阅读时长：{(index - 1) * 0.5}分钟。", PUSH_METHOD)

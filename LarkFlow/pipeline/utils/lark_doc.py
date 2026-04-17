import os
import re
import json
import requests
from typing import Optional

def extract_doc_token(url: str) -> Optional[str]:
    """
    从飞书文档链接中提取 token
    支持的格式:
    - https://domain.feishu.cn/docx/doxcnxxxxxxxxxxxxxxxx
    - https://domain.feishu.cn/wiki/wikcnxxxxxxxxxxxxxxxx
    """
    if not url:
        return None
        
    # 匹配 docx 格式
    match = re.search(r'/docx/([a-zA-Z0-9]+)', url)
    if match:
        return match.group(1)
        
    # 匹配 wiki 格式 (wiki 链接需要特殊的 API 获取真实 doc_token，这里简化处理)
    # 实际生产中可能需要调用 wiki API 获取底层的 obj_token
    match = re.search(r'/wiki/([a-zA-Z0-9]+)', url)
    if match:
        return match.group(1)
        
    return None

def get_tenant_access_token() -> str:
    """
    获取飞书 tenant_access_token
    """
    app_id = os.getenv("LARK_APP_ID")
    app_secret = os.getenv("LARK_APP_SECRET")
    
    if not app_id or not app_secret:
        raise ValueError("缺少 LARK_APP_ID 或 LARK_APP_SECRET 环境变量")
        
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {
        "app_id": app_id,
        "app_secret": app_secret
    }
    
    response = requests.post(url, json=payload)
    data = response.json()
    
    if data.get("code") != 0:
        raise Exception(f"获取 tenant_access_token 失败: {data}")
        
    return data.get("tenant_access_token")

def fetch_lark_doc_content(url: str) -> str:
    """
    读取飞书云文档 (docx) 和 Wiki 的纯文本内容
    """
    token = extract_doc_token(url)
    if not token:
        return f"无法从链接 {url} 中提取文档 token，请确保是有效的飞书 docx 或 wiki 链接。"
        
    try:
        access_token = get_tenant_access_token()
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        
        # 如果是 wiki 链接，需要先通过 wiki 节点获取真实的 obj_token (即 docx 的 token)
        if "/wiki/" in url:
            wiki_api_url = f"https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node?token={token}"
            wiki_resp = requests.get(wiki_api_url, headers=headers)
            wiki_data = wiki_resp.json()
            
            if wiki_data.get("code") == 0:
                # 获取真实的文档 token
                obj_token = wiki_data.get("data", {}).get("node", {}).get("obj_token")
                if obj_token:
                    token = obj_token
                else:
                    return f"读取 Wiki 节点失败: 无法获取底层的 obj_token"
            else:
                # 如果获取节点失败，可能是因为权限问题。
                # 飞书 API 要求应用必须被显式授权访问该文档。
                return f"读取 Wiki 节点失败 (Code: {wiki_data.get('code')}): {wiki_data.get('msg')}。请确保已在飞书文档右上角将应用（LarkFlow 引擎）添加为协作者！"
        
        # 调用获取文档纯文本 API (使用 docx 的 token)
        api_url = f"https://open.feishu.cn/open-apis/docx/v1/documents/{token}/raw_content"
        
        response = requests.get(api_url, headers=headers)
        data = response.json()
        
        if data.get("code") == 0:
            content = data.get("data", {}).get("content", "")
            return content
        else:
            return f"读取飞书文档失败 (Code: {data.get('code')}): {data.get('msg')}"
            
    except Exception as e:
        return f"读取飞书文档时发生异常: {str(e)}"

import requests
import json
base_url = 'http://192.168.1.200:8090/v1'
api_key = 'ah-1ba07271e2e56b338c513858e1523c783b543de5a6f1c24329f37582178d0d65'
messages = [
    {'role': 'user', 'content': 'What is the weather in Shanghai?'},
    {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call_123', 'type': 'function', 'function': {'name': 'weather', 'arguments': '{"query":"Shanghai"}'}}]},
    {'role': 'tool', 'name': 'weather', 'tool_call_id': 'call_123', 'content': 'Sunny'}
]
r = requests.post(f'{base_url}/chat/completions', json={'model': 'mimo-v2.5-pro', 'messages': messages}, headers={'Authorization': f'Bearer {api_key}'})
print(r.status_code, r.text)

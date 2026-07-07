import requests

url = 'http://127.0.0.1:8080/api/analyze'
data = {'url': 'https://www.xvideos.com/video.otuviud0d3e/ela_mostrou_como_pode_trabalhar_com_as_maos_para_sua_amiga_-_amelie_dubon_-_-_xvideoscom_officialxvred'}

res = requests.post(url, json=data)
print("Status:", res.status_code)
res_json = res.json()
print("Title:", res_json.get('title'))
print("Total Media Items:", len(res_json.get('media', [])))
for item in res_json.get('media', []):
    print("-----")
    print("Type:", item.get('type'))
    print("URL:", item.get('url'))
    print("Filename:", item.get('filename'))
    print("Source:", item.get('source'))

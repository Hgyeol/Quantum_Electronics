from bs4 import BeautifulSoup
import requests

url = 'https://n.news.naver.com/mnews/article/016/0002629035?sid=101'

res = requests.get(url)

soup = BeautifulSoup(res.text, 'html.parser')

article = soup.find('article', id='dic_area')
print(article.get_text(separator='\n', strip=True))
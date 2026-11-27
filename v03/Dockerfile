FROM python:3.12-slim
WORKDIR /app
COPY v02/requirements.txt v02/model-requirements.txt ./v02/
COPY v03/requirements.txt ./v03/
RUN pip install --no-cache-dir -r v03/requirements.txt -r v02/model-requirements.txt
COPY bf26.py verify_offer.py ./
COPY data/real_cases_2026_11_26 ./data/real_cases_2026_11_26
COPY v02 ./v02
COPY v03 ./v03
CMD ["python","-m","uvicorn","v03.api:app","--host","0.0.0.0","--port","8000"]

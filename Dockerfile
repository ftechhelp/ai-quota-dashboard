FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .

RUN pip install --no-cache-dir streamlit requests

COPY *.py ./

RUN mkdir -p /data

EXPOSE 8501

# collector.py samples usage history in the background; Streamlit serves the UI
CMD ["sh", "-c", "python collector.py & exec streamlit run app.py \
     --server.address=0.0.0.0 \
     --server.port=8501 \
     --server.headless=true \
     --server.enableCORS=false \
     --server.enableXsrfProtection=false"]

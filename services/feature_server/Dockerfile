FROM python:3.12-alpine
WORKDIR /app
COPY app.py /app/app.py
COPY area_features.json /app/area_features.json
EXPOSE 8080
CMD ["python", "-u", "app.py"]

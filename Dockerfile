FROM python:3.12-slim

WORKDIR /app
COPY railway/start.sh /app/start.sh
RUN chmod +x /app/start.sh

CMD ["/app/start.sh"]

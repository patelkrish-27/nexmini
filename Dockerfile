FROM python:3.12-slim

WORKDIR /app
COPY railway /app/railway
RUN chmod +x /app/railway/*.sh

# Default is Account 1. Railway service start commands select the
# appropriate script explicitly for each service.
CMD ["/app/railway/account1-friday.sh"]

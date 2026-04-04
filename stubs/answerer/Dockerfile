FROM node:20-alpine

RUN npm install -g @stoplight/prism-cli

WORKDIR /app
COPY specs/ ./specs/

EXPOSE 4010

CMD ["prism", "mock", "specs/answerer-service.yaml", "--host", "0.0.0.0", "--port", "4010", "--dynamic"]

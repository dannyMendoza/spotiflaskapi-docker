# Python SpotifyApi Call
FROM python:3.11.7-slim
ARG user="DM"
ARG email="dm.dmnix@gmail.com"
LABEL "Mantainer"=$user
LABEL "MantainerEmail"=$email
ENV APP /data/app
WORKDIR $APP
RUN pwd
COPY . .
RUN pip install --upgrade -r requierements.txt
EXPOSE 8080
EXPOSE 8888
CMD ["python", "app.py"]

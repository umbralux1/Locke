FROM postgres:15.4

USER postgres

COPY postgresql.conf /etc

CMD ["postgres", "-c", "config_file=/etc/postgresql.conf"]

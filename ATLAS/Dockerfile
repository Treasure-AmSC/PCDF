FROM python:3.13-alpine

LABEL org.opencontainers.image.source="https://github.com/Treasure-AmSC/PCDF"
LABEL org.opencontainers.image.description="ATLAS PCDF ntuple wizard"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/pcdf

COPY ATLAS/serve-ntuple-wizard.py ATLAS/ntuple-wizard.html \
    ATLAS/ntuple-wizard.css ATLAS/ntuple-wizard.js \
    ATLAS/ntuple-wizard.objects.json ATLAS/
COPY ATLAS/templates/ ATLAS/templates/

USER 65532:65532

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).read()"]

ENTRYPOINT ["python", "ATLAS/serve-ntuple-wizard.py"]
CMD ["--host", "0.0.0.0", "--port", "8080", "--no-browser"]

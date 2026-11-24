# TEST ONLY. Headless Chromium (Playwright) that takes the screenshots of docs/quick-start.md and
# docs/user-guide.md from the running test stack. See ../README.md, section "Screenshots".
FROM python:3.13.18-slim
RUN pip install -q --root-user-action=ignore --disable-pip-version-check playwright==1.55.0 \
 && playwright install --with-deps --only-shell chromium \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /w
COPY *.py /w/

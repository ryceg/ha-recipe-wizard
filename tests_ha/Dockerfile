# Home Assistant's test harness imports homeassistant.runner, which imports
# fcntl -- Unix only. So the integration tests cannot run on Windows at all.
# This image is the runner: the repo is mounted in, nothing is installed on the
# host, and it matches what CI would use.
FROM python:3.14
RUN pip install --no-cache-dir pytest-homeassistant-custom-component
# The todo platform pulls in homeassistant.components.todo, which registers
# intents and so imports homeassistant.components.conversation. That component
# declares its own requirements in its manifest, which the harness does not
# install, so anything loading a todo entity needs them here. Conversation in
# turn imports camera, which is what PyTurboJPEG is for -- a missing one arrives
# as an unrelated ModuleNotFoundError ("No module named 'turbojpeg'") rather
# than as anything about a todo list. The list matches .github/workflows/ci.yml,
# so a green container and a green CI mean the same thing.
RUN pip install --no-cache-dir hassil home-assistant-intents mutagen PyTurboJPEG
WORKDIR /app

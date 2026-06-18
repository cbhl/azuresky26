#!/usr/bin/env bash
zola build
rsync -rv --delete-before public/ cbhl_cbhl26z@ssh.nyc1.nearlyfreespeech.net:

#!/bin/sh
set -eu

repository_root=$(cd "${KNOWLEDGE_REPO_PATH:-/workspace}" && pwd -P)
git_user_name=${KB_GIT_USER_NAME:-KnowledgeBase}
git_user_email=${KB_GIT_USER_EMAIL:-knowledgebase@localhost}
home=${HOME:-/tmp/knowledgebase-home}

mkdir -p "$home"
export HOME="$home"

git config --global --add safe.directory "$repository_root"
git config --global user.name "$git_user_name"
git config --global user.email "$git_user_email"

exec uvicorn backend.app.main:app "$@"

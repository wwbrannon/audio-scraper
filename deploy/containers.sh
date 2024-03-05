#!/bin/bash

set -Eeuo pipefail

## We need the account ID for repo URLs
AWS_ACCOUNT_ID="$(aws sts get-caller-identity | jq -r .Account)"
export AWS_ACCOUNT_ID

## Repos under images/ we should work on
declare -a target_repos
target_repos=($(find images/ -mindepth 1 -maxdepth 1 -type d -exec basename {} \;))

## Which repos already exist?
declare -a current_repos
lines="$(aws ecr describe-repositories | jq -r '.repositories[] | .repositoryName')"
mapfile -t current_repos <<< "$lines"

## Docker login to be able to push
eval "$(aws ecr get-login --no-include-email)"

for target in "${target_repos[@]}"; do
    echo "Building and pushing Docker image $target"
    rname="${ApplicationName}/${target}"
    repo_url="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com/$rname:latest"

    repo_exists=0
    for c in "${current_repos[@]}"; do
        if [ "$c" == "$rname" ]; then
            repo_exists=1  # already exists
            break
        fi
    done

    if [ "$repo_exists" -eq 0 ]; then
        echo "Creating repo $rname"
        aws ecr create-repository --repository-name "$rname"
    fi

    docker build -t "$rname" images/"$target"
    docker tag "$rname:latest" "$repo_url"
    docker push "$repo_url"
done
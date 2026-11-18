#!/bin/sh
# Brings main of Tecso-Dev/caro -- what Vercel builds the site from until the
# switch to the server (docs/PHASE6_SETUP.md) -- to a commit of this
# repository's main: a fast-forward, never a force (docs/DELIVERY.md).
#
#   deploy/deliver.sh <this repository's checkout> <Tecso-Dev/caro's checkout> <commit>
#
# The images workflow's job `deliver` runs it once CI has passed on the
# commit. The first checkout is at the commit; the second has Tecso-Dev/caro
# as its origin, reached with the deploy key. Exit status:
# - 0 when that main is now the commit, or holds it already: a later merge
#   was delivered first;
# - 1 when that main has commits this one does not, which a person sorts
#   out, and nothing is pushed; or when GitHub refused the push.
set -eu
SRC=${1:?usage: deploy/deliver.sh <this checkout> <Tecso-Dev/caro checkout> <commit>}
DST=${2:?usage: deploy/deliver.sh <this checkout> <Tecso-Dev/caro checkout> <commit>}
SHA=${3:?usage: deploy/deliver.sh <this checkout> <Tecso-Dev/caro checkout> <commit>}
cd "$DST"

git fetch -q "$SRC" HEAD
got=$(git rev-parse FETCH_HEAD)
if [ "$got" != "$SHA" ]; then
    echo "deliver: $SRC is at $got, not $SHA; nothing pushed" >&2
    exit 1
fi
git fetch -q origin main
was=$(git rev-parse FETCH_HEAD)

if [ "$was" = "$SHA" ]; then
    echo "deliver: Tecso-Dev/caro main is $SHA already"
    exit 0
fi
if git merge-base --is-ancestor "$SHA" "$was"; then
    echo "deliver: Tecso-Dev/caro main is $was, which holds $SHA: a later merge was delivered first"
    exit 0
fi
if ! git merge-base --is-ancestor "$was" "$SHA"; then
    echo "deliver: Tecso-Dev/caro main ($was) has commits $SHA does not; nothing pushed" >&2
    exit 1
fi

# A push GitHub refuses -- the key without write, a rule on main -- exits
# non-zero, and with it this script.
git push -q origin "$SHA:refs/heads/main"
echo "deliver: Tecso-Dev/caro main $was -> $SHA"

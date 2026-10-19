# lgsf-web

## Development Install

### Dependencies
```sh
uv sync
npm ci
```

### DB

```sh
createuser lgsf_web --pwprompt --createdb
createdb lgsf_web -O lgsf_web
```

```sh
cp .env.example .env
```

Make `DB_USER=lgsf_web` and `DB_PASSWORD` whatever you set for the `lgsf_web` postgres user.

### Load data from RDS

Get values from Parameter Store, dump the db, and restore it, and migrate.

```sh
export AWS_PROFILE=dev-lgsf-dc
param() { aws ssm get-parameter --region eu-west-2 --name "$1" --query Parameter.Value --output text; }

PGPASSWORD="$(param DB_PASSWORD)" pg_dump \
  -h "$(param DB_HOST)" -U "$(param DB_USER)" -d "$(param DB_NAME)" \
  -Fc --no-owner --no-acl -f lgsf_web.dump

pg_restore -h 127.0.0.1 -U lgsf_web -d lgsf_web --no-owner --no-acl lgsf_web.dump

uv run manage.py migrate
```

If you already have data in the db, then add `--clean --if-exists`.

## Tests

```sh
uv run pytest
```

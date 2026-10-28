.PHONY: all preflight build up down restart logs status deploy caddy-validate caddy-reload test clean

all: deploy

preflight:
	bash deploy/scripts/preflight.sh

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose restart

logs:
	docker compose logs -f --tail=100

status:
	docker compose ps
	@echo "--- Container Stats ---"
	docker stats --no-stream stocknomist-app || true
	@echo "--- Container Top Processes ---"
	docker top stocknomist-app || true
	@echo "--- Local Health Status ---"
	curl -s http://127.0.0.1:18800/health

deploy:
	bash deploy/scripts/deploy.sh

caddy-validate:
	caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

caddy-reload: caddy-validate
	systemctl reload caddy

test:
	@echo "==> Testing Loopback Health (127.0.0.1:18800/health)..."
	curl -I http://127.0.0.1:18800/health
	@echo "==> Testing Public TLS Health Bypass (no auth)..."
	curl -I https://stocknomist.168-222-27-36.sslip.io/health
	@echo "==> Testing Public Auth Protection (expect 401)..."
	curl -I https://stocknomist.168-222-27-36.sslip.io/
	@echo "==> Testing Authenticated Access (admin:stocknomist2026, expect 200)..."
	curl -I -u admin:stocknomist2026 https://stocknomist.168-222-27-36.sslip.io/

clean:
	docker compose down --volumes --remove-orphans

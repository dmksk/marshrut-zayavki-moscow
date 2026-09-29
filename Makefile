.PHONY: run max-demo test seed train data

run:
	@if [ "$${APP_PUBLIC:-0}" = "1" ] && [ -z "$${APP_ADMIN_KEY:-}" ]; then echo "Set a strong APP_ADMIN_KEY for public mode" >&2; exit 1; fi
	APP_ADMIN_KEY=$${APP_ADMIN_KEY:-hackathon-demo} python3 -m app.server

max-demo:
	python3 -m app.max_polling

test:
	python3 -m unittest discover -s tests -v

seed:
	python3 scripts/seed_demo.py

train:
	python3 scripts/train_model.py

data:
	python3 scripts/generate_dataset.py

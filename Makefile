.PHONY: run test seed train data

run:
	APP_ADMIN_KEY=$${APP_ADMIN_KEY:-hackathon-demo} python3 -m app.server

test:
	python3 -m unittest discover -s tests -v

seed:
	python3 scripts/seed_demo.py

train:
	python3 scripts/train_model.py

data:
	python3 scripts/generate_dataset.py

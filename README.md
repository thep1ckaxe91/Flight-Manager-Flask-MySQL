# Flight Manager

## How to run
Open your CLI, make sure docker was installed
```bash
docker-compose up --build
```
Attach shell to backend container and exec:
```bash
flask db upgrade
```
Your app now should running in localhost:5000

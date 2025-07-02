from ray import serve
from .app import app

@serve.deployment()
@serve.ingress(app)
class Auth:
	pass


ray_app = Auth.bind()

if __name__ == '__main__':
	serve.run(ray_app, blocking=True)  # import uvicorn  # uvicorn.run("app:app", reload=True)

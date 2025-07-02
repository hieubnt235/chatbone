from .app import app
from ray import serve

@serve.deployment()
@serve.ingress(app)
class Datastore:
	pass


ray_app = Datastore.bind()

if __name__ == '__main__':
	serve.run(ray_app, blocking=True)

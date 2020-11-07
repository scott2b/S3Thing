# S3Thing
A proof-of-concept for S3 download purchasing via Stripe


## run

```
 $ gunicorn -b :5000 --workers 3 --reload wsgi:application
```

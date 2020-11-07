import os
import shutil
import sys
import secrets
import time
from typing import Optional
import boto3
from botocore.exceptions import ClientError
from flask import Flask, redirect, request, jsonify, session
from flask import make_response, render_template
import stripe
from dotenv import load_dotenv

load_dotenv()

import sqlite3


DB = 'db.db'
DOMAIN = os.environ['DOMAIN']
AWS_PROFILE = os.environ['AWS_PROFILE']
BUCKET = os.environ['BUCKET']
PREFIX = os.environ['PREFIX']
STRIPE_KEY = os.environ['STRIPE_KEY']
STRIPE_SECRET = os.environ['STRIPE_SECRET']
WEBHOOK_SECRET = os.environ['WEBHOOK_SECRET']
LINK_TIMEOUT = 3600

stripe.api_key = STRIPE_SECRET

app = Flask(__name__)

s3 = boto3.session.Session(
    profile_name=AWS_PROFILE).client('s3')


def create_presigned_url(
        bucket_name: str, object_name: str, expiration=LINK_TIMEOUT
    ) -> Optional[str]:
    """From:
    https://dev.to/idrisrampurawala/share-your-aws-s3-private-content-with-others-without-making-it-public-4k59

    Generate a presigned URL to share an s3 object

    Arguments:
        bucket_name {str} -- Required. s3 bucket of object to share
        object_name {str} -- Required. s3 object to share

    Keyword Arguments:
        expiration {int} -- Expiration in seconds (default: {3600})

    Returns:
        Optional[str] -- Presigned url of s3 object. If error, returns None.
    """
    try:
        # note that we are passing get_object as the operation to perform
        response = s3.generate_presigned_url('get_object',
                                                    Params={
                                                        'Bucket': bucket_name,
                                                        'Key': object_name
                                                    },
                                                    ExpiresIn=expiration)
    except ClientError as e:
        logging.error(e)
        return None
    return response


def generate_presigned_url(resource):
    bucket_name = BUCKET
    bucket_resource_url = f"{PREFIX}/{resource}"
    url = create_presigned_url(
        bucket_name,
        bucket_resource_url
    )
    return url


@app.route('/success')
def payment_success():
    page = request.args.get('ref')
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    files = ''
    for i in range(5):
        row = c.execute("SELECT files FROM purchases where key=? AND fulfilled=1", (page,))
        row = row.fetchone()
        if row[0]:
            files = row[0].split(',')
            break
        time.sleep(1)
        print('Waiting...')
    conn.close()
    links = []
    for f in files:
        url = generate_presigned_url(f)
        links.append( (f, url) )
    return render_template('purchased.html', links=links)


@app.route('/fulfillment', methods=['POST'])
def fulfillment():
    """https://stripe.com/docs/payments/checkout/fulfill-orders"""
    payload = request.get_json()
    sig_header = request.headers['STRIPE_SIGNATURE']
    event = None
    # TODO the event verification below seems to be short-circuiting this function
    # while still returning a 200. This resource copy should really happen
    # after the verification step. There is an option in the docs to verify
    # the signature manually if needed.
    if payload['type'] == 'checkout.session.completed':
        _id = payload['data']['object']['client_reference_id']
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute(f"UPDATE purchases SET fulfilled=1 where key='{_id}'")
        conn.commit()
        conn.close()
    try:
      event = stripe.Webhook.construct_event(
        payload, sig_header, WEBHOOK_SECRET
      )
    except ValueError as e:
      return make_response(jsonify({}, 400))
    except stripe.error.SignatureVerificationError as e:
      return make_response(jsonify({}, 400))
    # is any of this being executed?
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
    sys.stdout.flush()
    return jsonify({'status': 'OK'})


@app.route('/cancel')
def payment_cancelled():
    return 'cancelled'


@app.route('/create-session', methods=['POST'])
def create_checkout_session():
    """From: https://stripe.com/docs/checkout/integration-builder"""
    data = request.get_json()
    resources = ','.join(data['lineItems'])
    ref_id = secrets.token_urlsafe(10)
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[
                {
                    'price_data': {
                        'currency': 'usd',
                        'unit_amount': 100,
                        'product_data': {
                            'name': f'S3 Resources: {resources}'
                        },
                    },
                    'quantity': len(data['lineItems']),
                },
            ],
            client_reference_id=ref_id,
            mode='payment',
            success_url=DOMAIN + f'/success?ref={ref_id}',
            cancel_url=DOMAIN + '/cancel.html',
        )
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute(f"INSERT INTO purchases VALUES ('{ref_id}','{resources}', 0)")
        conn.commit()
        conn.close()
        return jsonify({'id': checkout_session.id})
    except Exception as e:
        raise
        return jsonify(error=str(e)), 403


@app.route('/')
def checkout():
    files = s3.list_objects(Bucket=BUCKET, Prefix=PREFIX)
    files = [item['Key'] for item in files['Contents'] if not item['Key'].endswith('/')]
    files = [item.split('/')[1] for item in files]
    return render_template('checkout.html', stripe_key=STRIPE_KEY, files=files,
        bucket=BUCKET, prefix=PREFIX)

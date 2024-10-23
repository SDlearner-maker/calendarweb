from flask import Flask, render_template, redirect, url_for, request, session, flash, jsonify
import firebase_admin
from flask_mail import Mail, Message
from firebase_admin import credentials, initialize_app, firestore, auth
import csv
import json
from io import StringIO
import datetime
import os
from apscheduler.schedulers.background import BackgroundScheduler
import smtplib
from email.mime.text import MIMEText
from flask_cors import CORS

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

app.secret_key = ''  # Change this to a secure key

# Configure Flask-Mail
app.config['MAIL_SERVER'] = 'smtp.gmail.com'  # For Gmail
app.config['MAIL_PORT'] = 465
app.config['MAIL_USERNAME'] = ""
app.config['MAIL_PASSWORD'] = ""
app.config['MAIL_USE_TLS'] = False
app.config['MAIL_USE_SSL'] = True

mail = Mail(app)

# Initialize Firebase Admin
cred = credentials.Certificate('serviceAccountKey.json')
firebase_admin.initialize_app(cred)

# Initialize Firestore
db = firestore.client()

# Initialize APScheduler
scheduler = BackgroundScheduler()
scheduler.start()

# Function to send email
def send_email_reminder(sender, receiver):
    to_email = receiver
    subject = "Email Reminder"
    body = "This is a reminder email sent from Flask application."

    # Create the email message
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = receiver

    try:
        with smtplib.SMTP(app.config['MAIL_SERVER'], app.config['MAIL_PORT']) as server:
            server.starttls()
            server.login(app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
            server.sendmail(app.config['MAIL_USERNAME'], to_email, msg.as_string())
            print("Email sent successfully!")
    except Exception as e:
        print(f"Failed to send email: {e}")

@app.route('/')
def home():
    return render_template('sign_in.html')

@app.route('/events', methods=['GET'])
def events_list():
    if 'user_id' not in session:
        return redirect(url_for('home'))

    user_email = session['user_email']
    events_ref = db.collection('events').document(user_email)

    # Retrieve events from Firestore
    if events_ref.get().exists:
        events = events_ref.get().to_dict()
    else:
        events = {}

    # Process events to separate date and time
    for event_index, event in events.items():
        # Assuming 'time' is stored as an ISO format string
        event_time = event.get("time")
        if event_time:
            dt = datetime.datetime.fromisoformat(event_time)
            event['date'] = dt.date().isoformat()  # Add date in 'YYYY-MM-DD' format
            event['time'] = dt.time().strftime('%H:%M')  # Add time in 'HH:MM' format

    return render_template('events_list.html', events=events)

@app.route('/event_form')
def event_form():
    if 'user_id' not in session:
        return redirect(url_for('home'))
    return render_template('event_form.html')

@app.route('/add_event', methods=['POST'])
def add_event():
    if 'user_id' not in session:
        return redirect(url_for('home'))

    user_email = session['user_email']

    event_data = {
        "title": request.form.get("title"),
        "description": request.form.get("description"),
        "receiverMail": request.form.get("receiverMail"),
        "time": f"{request.form.get('date')}T{request.form.get('time')}",  # Combine date and time
    }

    user_events_ref = db.collection('events').document(user_email)
    events_doc = user_events_ref.get()
    if events_doc.exists:
        events = events_doc.to_dict()
    else:
        events = {}

    next_index = str(len(events))
    events[next_index] = event_data

    # Correct way when importing the module:
    current_datetime = datetime.datetime.now()
    print("Current date and time:", current_datetime)

        
    user_events_ref.set(events)

    # Send email to the receiver
    send_email_to_receiver(event_data)

    flash('Event added successfully!', 'success')
    return redirect(url_for('events_list'))

@app.route('/delete_event/<event_index>', methods=['POST'])
def delete_event(event_index):
    if 'user_id' not in session:
        return redirect(url_for('home'))

    user_email = session['user_email']
    user_events_ref = db.collection('events').document(user_email)
    doc_snapshot = user_events_ref.get()
    if doc_snapshot.exists:
        events = doc_snapshot.to_dict()
        if event_index in events:
            # Get event details to send email before deleting
            event = events[event_index]
            receiver_email = event.get("receiverMail")
            event_title = event.get("title")

            del events[event_index]
            user_events_ref.set(events)

            # Send email to notify the receiver that the event has been deleted
            if receiver_email:
                try:
                    msg = Message(
                        f'Event Deleted: {event_title}',
                        sender=app.config['MAIL_USERNAME'],
                        recipients=[receiver_email]
                    )
                    msg.body = f'The event "{event_title}" has been deleted.'
                    mail.send(msg)
                    flash(f'Email sent to {receiver_email} about event deletion.', 'info')
                except Exception as e:
                    flash(f'Failed to send email: {e}', 'error')

            flash('Event deleted successfully!', 'success')
        else:
            flash('Event not found!', 'error')
    else:
        flash('No events found for this user!', 'error')

    return redirect(url_for('events_list'))

@app.route('/update_event/<event_index>', methods=['GET', 'POST'])
def update_event(event_index):
    if 'user_id' not in session:
        return redirect(url_for('home'))

    user_email = session['user_email']
    user_events_ref = db.collection('events').document(user_email)

    if request.method == 'POST':

        doc_snapshot = user_events_ref.get()
        if doc_snapshot.exists:
            events = doc_snapshot.to_dict()
            if event_index in events:
                # Get date and time from the form and combine them into an ISO 8601 timestamp
                updated_event = {
                    "title": request.form.get("title"),
                    "description": request.form.get("description"),
                    "receiverMail": events[event_index]['receiverMail'],  # Keep receiverMail unchanged
                    "time": f"{request.form.get('date')}T{request.form.get('time')}:00"  # Combine date and time
                }
                events[event_index] = updated_event

                user_events_ref.set(events)
                flash('Event updated successfully!', 'success')

                # Send email to notify the receiver of the updated event details
                receiver_email = events[event_index].get("receiverMail")
                if receiver_email:
                    try:
                        msg = Message(
                            f'Updated Event: {updated_event["title"]}',
                            sender=app.config['MAIL_USERNAME'],
                            recipients=[receiver_email]
                        )
                        msg.body = (f'The event "{updated_event["title"]}" has been updated with the following details:\n\n'
                                    f'Description: {updated_event["description"]}\n'
                                    f'Time: {updated_event["time"]}\n\n'
                                    'Please take note of the changes.')
                        mail.send(msg)
                        flash(f'Email sent to {receiver_email} about the updated event.', 'info')
                    except Exception as e:
                        flash(f'Failed to send email: {e}', 'error')               
                
            else:
                flash('Event not found!', 'error')
        return redirect(url_for('events_list'))

    #pre-fill the form after fetching data
    doc_snapshot = user_events_ref.get()
    if doc_snapshot.exists:
        events = doc_snapshot.to_dict()
        event = events.get(event_index, None)

        if event:
            # Split the stored time into separate date and time for editing
            dt = datetime.datetime.fromisoformat(event['time'])
            event['date'] = dt.date().isoformat()
            event['time'] = dt.time().strftime('%H:%M')

    else:
        event = None

    return render_template('update_event.html', event=event, event_index=event_index)


@app.route('/import_events', methods=['POST'])
def import_events():
    if 'user_id' not in session:
        return redirect(url_for('home'))

    csv_file = request.files['csv_file']
    user_email = session['user_email']
    
    if csv_file and csv_file.filename.endswith('.csv'):
        csv_data = csv_file.read().decode('utf-8')
        csv_reader = csv.DictReader(StringIO(csv_data))

        # Normalize headers by stripping whitespace
        csv_reader.fieldnames = [field.strip() for field in csv_reader.fieldnames]

        user_events_ref = db.collection('events').document(user_email)
        existing_events = user_events_ref.get().to_dict() or {}

        for row in csv_reader:
            print(row)  # Print each row to see what you're getting

            # Extracting date and time from CSV
            event_date = row.get("date")  # Assuming the CSV has a column named 'date'
            event_time = row.get("time")  # Assuming the CSV has a column named 'time'
            
            # Validate the date and time
            try:
                # Combine date and time into a single string
                combined_datetime_str = f"{event_date} {event_time}"  # Combined without 'T'

                # Parse the combined datetime string (Assuming format is YYYY-MM-DD HH:MM)
                combined_datetime = datetime.datetime.strptime(combined_datetime_str, '%Y-%m-%d %H:%M')

                # Check if the date is in the future
                if combined_datetime.date() < datetime.datetime.now().date():
                    flash(f'Event on {combined_datetime.date()} is in the past and will be skipped.', 'warning')
                    continue  # Skip this event

            except ValueError:
                flash(f'Invalid date or time format in row: {row}. Event will be skipped.', 'error')
                continue  # Skip this event

            # Create new event
            new_event = {
                "title": row.get("title"),
                "description": row.get("description"),
                "receiverMail": row.get("receiverMail"),
                "time": combined_datetime.isoformat(),  # Use ISO format for Firestore
            }
            
            print(new_event)  # Check new_event values
            send_email_to_receiver(new_event)

            # Use a sequential index for existing events
            next_index = str(len(existing_events))
            existing_events[next_index] = new_event

        # Save the updated events to Firestore
        user_events_ref.set(existing_events)
        flash('Events imported successfully!', 'success')
    else:
        flash('Invalid file format. Please upload a CSV file.', 'error')

    return redirect(url_for('events_list'))

def send_email_to_receiver(event):
    receiver_email = event.get("receiverMail")
    if receiver_email:
        try:
            msg = Message(
                subject=event.get("title"),
                sender=app.config['MAIL_USERNAME'],
                recipients=[receiver_email]
            )
            msg.body = f"Description: {event.get('description')}\nTime: {event.get('time')}"
            mail.send(msg)
            print(f"Email sent to {receiver_email} for event: {event.get('title')}")
        except Exception as e:
            print(f"Failed to send email to {receiver_email}: {e}")

@app.route('/verify_google_token', methods=['POST'])
def verify_google_token():
    token = request.json.get('token')
    try:
        decoded_token = auth.verify_id_token(token)
        session['user_id'] = decoded_token['uid']
        session['user_email'] = decoded_token['email']
        return '', 200
    except Exception as e:
        print("Error verifying token:", e)
        return '', 403


@app.route('/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)  # Remove user ID from session
    session.pop('user_email', None)  # Remove user email from session
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)

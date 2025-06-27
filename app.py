import os
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import CheckConstraint, func, and_, or_
from sqlalchemy.orm import validates
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta
import csv
from io import StringIO
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Cấu hình database
app.config['SQLALCHEMY_DATABASE_URI'] = f"mysql+mysqlconnector://{os.getenv('MYSQL_USER')}:{os.getenv('MYSQL_PASSWORD')}@{os.getenv('MYSQL_HOST')}/{os.getenv('MYSQL_DB')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Định nghĩa các model
class Flight(db.Model):
    __tablename__ = 'flights'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    flight_code = db.Column(db.String(10), unique=True, nullable=False)
    departure = db.Column(db.String(50), nullable=False)
    destination = db.Column(db.String(50), nullable=False)
    departure_time = db.Column(db.DateTime, nullable=False)
    arrival_time = db.Column(db.DateTime, nullable=False)
    price = db.Column(db.Numeric(10,2), nullable=False)
    
    __table_args__ = (
        CheckConstraint('arrival_time > departure_time', name='check_arrival_after_departure'),
    )
    
    @validates('flight_code')
    def validate_flight_code(self, key, code):
        if not 3 <= len(code) <= 10:
            raise ValueError('Flight code must be 3-10 characters')
        return code

class Passenger(db.Model):
    __tablename__ = 'passengers'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    phone = db.Column(db.String(15), nullable=False)
    dob = db.Column(db.Date, nullable=False)
    passport_no = db.Column(db.String(20), unique=True, nullable=False)
    
    @validates('email')
    def validate_email(self, key, email):
        if '@' not in email or '.' not in email.split('@')[-1]:
            raise ValueError('Invalid email format')
        return email
    
    @validates('phone')
    def validate_phone(self, key, phone):
        if not phone.isdigit() or not 10 <= len(phone) <= 15:
            raise ValueError('Phone must be 10-15 digits')
        return phone
    
    @validates('passport_no')
    def validate_passport(self, key, passport):
        if not (6 <= len(passport) <= 20 and passport.isalnum()):
            raise ValueError('Passport must be 6-20 alphanumeric characters')
        return passport

class Ticket(db.Model):
    __tablename__ = 'tickets'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    passenger_id = db.Column(db.Integer, db.ForeignKey('passengers.id'), nullable=False)
    flight_id = db.Column(db.Integer, db.ForeignKey('flights.id'), nullable=False)
    seat_no = db.Column(db.String(5), nullable=False)
    booked_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        db.UniqueConstraint('passenger_id', 'flight_id', name='unique_passenger_flight'),
    )
    
    passenger = db.relationship('Passenger', backref='tickets')
    flight = db.relationship('Flight', backref='tickets')

# Routes
@app.route('/')
def index():
    return redirect(url_for('list_flights'))

@app.route('/flights')
def list_flights():
    departure_filter = request.args.get('departure')
    destination_filter = request.args.get('destination')
    date_filter = request.args.get('date')
    
    query = Flight.query
    
    if departure_filter:
        query = query.filter(Flight.departure.ilike(f'%{departure_filter}%'))
    if destination_filter:
        query = query.filter(Flight.destination.ilike(f'%{destination_filter}%'))
    if date_filter:
        try:
            filter_date = datetime.strptime(date_filter, '%Y-%m-%d').date()
            query = query.filter(db.func.date(Flight.departure_time) == filter_date)
        except ValueError:
            pass
    
    flights = query.all()
    return render_template('flights.html', flights=flights)

@app.route('/flights/add', methods=['GET', 'POST'])
def add_flight():
    if request.method == 'POST':
        try:
            flight = Flight(
                flight_code=request.form['flight_code'],
                departure=request.form['departure'],
                destination=request.form['destination'],
                departure_time=datetime.strptime(request.form['departure_time'], '%Y-%m-%dT%H:%M'),
                arrival_time=datetime.strptime(request.form['arrival_time'], '%Y-%m-%dT%H:%M'),
                price=float(request.form['price'])
            )
            db.session.add(flight)
            db.session.commit()
            return redirect(url_for('list_flights'))
        except (ValueError, IntegrityError) as e:
            db.session.rollback()
            error = str(e)
            return render_template('add_flight.html', error=error)
    
    return render_template('add_flight.html')

@app.route('/passengers/add', methods=['GET', 'POST'])
def add_passenger():
    if request.method == 'POST':
        try:
            passenger = Passenger(
                full_name=request.form['full_name'],
                email=request.form['email'],
                phone=request.form['phone'],
                dob=datetime.strptime(request.form['dob'], '%Y-%m-%d').date(),
                passport_no=request.form['passport_no']
            )
            db.session.add(passenger)
            db.session.commit()
            return redirect(url_for('book_ticket'))
        except (ValueError, IntegrityError) as e:
            db.session.rollback()
            error = str(e)
            return render_template('add_passenger.html', error=error)
    
    return render_template('add_passenger.html')

@app.route('/tickets/book', methods=['GET', 'POST'])
def book_ticket():
    if request.method == 'POST':
        passenger_id = request.form['passenger_id']
        flight_id = request.form['flight_id']
        seat_no = request.form['seat_no']
        
        try:
            # Kiểm tra tuổi
            passenger = Passenger.query.get(passenger_id)
            if (datetime.now().date() - passenger.dob) < timedelta(days=365*2):
                raise ValueError('Passenger must be at least 2 years old')
            
            # Kiểm tra ghế ngồi
            existing_seat = Ticket.query.filter_by(flight_id=flight_id, seat_no=seat_no).first()
            if existing_seat:
                raise ValueError('Seat already taken')
            
            # Kiểm tra chuyến bay đã khởi hành chưa
            flight = Flight.query.get(flight_id)
            if flight.departure_time < datetime.now():
                raise ValueError('Cannot book past flights')
            
            ticket = Ticket(
                passenger_id=passenger_id,
                flight_id=flight_id,
                seat_no=seat_no
            )
            db.session.add(ticket)
            db.session.commit()
            return redirect(url_for('list_tickets'))
        except (ValueError, IntegrityError) as e:
            db.session.rollback()
            error = str(e)
            passengers = Passenger.query.all()
            flights = Flight.query.filter(Flight.departure_time > datetime.now()).all()
            return render_template('book_ticket.html', passengers=passengers, flights=flights, error=error)
    
    passengers = Passenger.query.all()
    flights = Flight.query.filter(Flight.departure_time > datetime.now()).all()
    return render_template('book_ticket.html', passengers=passengers, flights=flights)

@app.route('/tickets')
def list_tickets():
    tickets = Ticket.query.join(Passenger).join(Flight).all()
    return render_template('tickets.html', tickets=tickets)

@app.route('/tickets/export/<int:flight_id>')
def export_tickets(flight_id):
    tickets = Ticket.query.filter_by(flight_id=flight_id).join(Passenger).join(Flight).all()
    
    # Tạo file CSV trong bộ nhớ
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Passenger', 'Flight Code', 'Seat', 'Price', 'Booked At'])
    for ticket in tickets:
        writer.writerow([
            ticket.passenger.full_name,
            ticket.flight.flight_code,
            ticket.seat_no,
            ticket.flight.price,
            ticket.booked_at.strftime('%Y-%m-%d %H:%M')
        ])
    
    output.seek(0)
    return send_file(
        output,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'tickets_{flight_id}.csv'
    )

@app.route('/report/popular-routes')
def popular_routes():
    routes = db.session.query(
        Flight.departure,
        Flight.destination,
        db.func.count(Ticket.id).label('ticket_count'),
        db.func.sum(Flight.price).label('total_revenue')
    ).join(Ticket).group_by(Flight.departure, Flight.destination).order_by(db.desc('ticket_count')).all()
    
    return render_template('popular_routes.html', routes=routes)

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
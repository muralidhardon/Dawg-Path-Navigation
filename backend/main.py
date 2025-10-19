from flask import Flask, request, jsonify
from flask_cors import CORS
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}}, 
     methods=["GET", "POST", "OPTIONS"],
     allow_headers=["Content-Type"])

# SQLite database (creates file automatically, no setup needed)
DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'safety_app.db')
engine = create_engine(f'sqlite:///{DATABASE_PATH}')
Session = sessionmaker(bind=engine)
Base = declarative_base()

# ===== DATABASE MODELS =====

class Event(Base):
    __tablename__ = 'events'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    event_type = Column(String(100), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    time = Column(DateTime, nullable=False)
    notes = Column(String(1000))
    created_at = Column(DateTime, default=datetime.utcnow)
    user_lat = Column(Float)
    user_lng = Column(Float)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'type': self.event_type,
            'location': {'lat': self.latitude, 'lng': self.longitude},
            'time': self.time.isoformat(),
            'notes': self.notes,
            'timestamp': self.created_at.isoformat(),
            'userLocation': {'lat': self.user_lat, 'lng': self.user_lng}
        }

class CrowdLocation(Base):
    __tablename__ = 'crowd_locations'
    
    id = Column(Integer, primary_key=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    reports = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    user_lat = Column(Float)
    user_lng = Column(Float)
    
    def to_dict(self):
        return {
            'id': self.id,
            'location': {'lat': self.latitude, 'lng': self.longitude},
            'timestamp': self.created_at.isoformat(),
            'reports': self.reports,
            'userLocation': {'lat': self.user_lat, 'lng': self.user_lng}
        }

class DangerZone(Base):
    __tablename__ = 'danger_zones'
    
    id = Column(Integer, primary_key=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    radius = Column(Float, nullable=False)
    danger_level = Column(Integer, nullable=False)
    reports = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    user_lat = Column(Float)
    user_lng = Column(Float)
    
    def to_dict(self):
        return {
            'id': self.id,
            'location': {'lat': self.latitude, 'lng': self.longitude},
            'radius': self.radius,
            'dangerLevel': self.danger_level,
            'timestamp': self.created_at.isoformat(),
            'reports': self.reports,
            'userLocation': {'lat': self.user_lat, 'lng': self.user_lng}
        }

# Create all tables
Base.metadata.create_all(engine)

# ===== ROUTES =====

@app.route('/api/add-event', methods=['POST'])
def add_event():
    try:
        data = request.json
        session = Session()
        
        event = Event(
            name=data['name'],
            event_type=data['type'],
            latitude=data['location']['lat'],
            longitude=data['location']['lng'],
            time=datetime.fromisoformat(data['time']),
            notes=data.get('notes', ''),
            user_lat=data['userLocation']['lat'],
            user_lng=data['userLocation']['lng']
        )
        
        session.add(event)
        session.commit()
        result = event.to_dict()
        session.close()
        
        return jsonify({'success': True, 'data': result}), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/report-crowd', methods=['POST'])
def report_crowd():
    try:
        data = request.json
        session = Session()
        
        crowd = CrowdLocation(
            latitude=data['location']['lat'],
            longitude=data['location']['lng'],
            user_lat=data['userLocation']['lat'],
            user_lng=data['userLocation']['lng']
        )
        session.add(crowd)
        session.commit()
        result = crowd.to_dict()
        session.close()
        
        return jsonify({'success': True, 'data': result}), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/report-danger', methods=['POST'])
def report_danger():
    try:
        data = request.json
        session = Session()
        
        danger = DangerZone(
            latitude=data['location']['lat'],
            longitude=data['location']['lng'],
            radius=data['radius'],
            danger_level=data['dangerLevel'],
            user_lat=data['userLocation']['lat'],
            user_lng=data['userLocation']['lng']
        )
        session.add(danger)
        session.commit()
        result = danger.to_dict()
        session.close()
        
        return jsonify({'success': True, 'data': result}), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/api/events', methods=['GET'])
def get_events():
    try:
        session = Session()
        events = session.query(Event).all()
        result = [event.to_dict() for event in events]
        session.close()
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/crowds', methods=['GET'])
def get_crowds():
    try:
        session = Session()
        crowds = session.query(CrowdLocation).all()
        result = [crowd.to_dict() for crowd in crowds]
        session.close()
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/dangers', methods=['GET'])
def get_dangers():
    try:
        session = Session()
        dangers = session.query(DangerZone).all()
        result = [danger.to_dict() for danger in dangers]
        session.close()
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'Backend is running'}), 200

if __name__ == '__main__':
    app.run(debug=True, port=8000)
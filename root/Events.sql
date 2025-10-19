-- Create table
CREATE TABLE uw_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    location TEXT NOT NULL,
    date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    organizer TEXT NOT NULL,
    description TEXT
);

-- Insert 20 random UW Seattle campus events
INSERT INTO uw_events (title, location, date, start_time, end_time, organizer, description) VALUES
('Husky Startup Panel', 'HUB 145', '2025-10-20', '17:00', '19:00', 'Foster School of Business', 'A panel of UW alumni sharing startup journeys and funding advice.'),
('Autumn Job & Internship Fair', 'HUB Ballroom', '2025-10-21', '11:00', '15:00', 'UW Career Center', 'Meet employers from across tech, healthcare, and research fields.'),
('CSE 143 Midterm Review', 'CSE2 G20', '2025-10-19', '18:00', '20:00', 'UW ACM', 'Study session for the upcoming CSE 143 midterm, with past exam problems.'),
('Campus Sustainability Tour', 'Drumheller Fountain', '2025-10-23', '13:00', '14:30', 'UW Sustainability Office', 'Guided tour highlighting eco-friendly campus projects.'),
('Film Screening: Everything Everywhere All at Once', 'HUB Auditorium', '2025-10-25', '19:00', '21:30', 'ASUW Arts & Entertainment', 'Free student movie night with popcorn provided.'),
('Bioengineering Research Expo', 'NanoES 160', '2025-10-24', '14:00', '17:00', 'Bioengineering Dept.', 'Undergraduate and graduate students present ongoing research projects.'),
('UW Jazz Ensemble Concert', 'Meany Hall', '2025-10-26', '19:30', '21:00', 'School of Music', 'Live performance by the UW Jazz Ensemble.'),
('Data Science Club Hack Night', 'Sieg 233', '2025-10-20', '18:30', '21:30', 'UW Data Science Club', 'Casual evening for data enthusiasts to code, share projects, and snack.'),
('Intramural Volleyball Finals', 'IMA Gym A', '2025-10-22', '18:00', '20:00', 'UW Rec Sports', 'Championship game for fall quarter volleyball league.'),
('Study Abroad Info Session', 'Odegaard 136', '2025-10-18', '16:00', '17:00', 'UW Study Abroad Office', 'Overview of international programs and scholarships.'),
('Environmental Film Festival', 'Alder Auditorium', '2025-10-27', '17:30', '20:30', 'Earth Club', 'Documentaries and discussions about climate action.'),
('Astronomy Night', 'Physics-Astronomy Rooftop Observatory', '2025-10-24', '21:00', '23:00', 'UW Astronomy Club', 'Telescope viewing and constellation spotting with experts.'),
('Women in STEM Networking Night', 'HUB 250', '2025-10-28', '18:00', '20:00', 'WINFO', 'Meet and connect with professionals and peers in STEM fields.'),
('Autumn Farmers Market', 'Red Square', '2025-10-19', '10:00', '14:00', 'ASUW', 'Local produce, food trucks, and campus crafts.'),
('Yoga on the Lawn', 'Denny Field', '2025-10-22', '09:00', '10:00', 'UW Rec Center', 'Free morning yoga session open to all students.'),
('Language Exchange Meetup', 'Suzzallo Café', '2025-10-23', '17:00', '18:30', 'UW International Club', 'Practice different languages and meet new friends.'),
('AI Ethics Lecture', 'Kane 130', '2025-10-29', '16:30', '18:00', 'Allen School of CSE', 'Guest lecture on ethics and accountability in artificial intelligence.'),
('Creative Writing Workshop', 'Padelford C101', '2025-10-20', '15:00', '17:00', 'English Department', 'Peer feedback and exercises on poetry and short fiction.'),
('Husky Robotics Demo Day', 'HUB 334', '2025-10-30', '14:00', '17:00', 'UW Robotics Club', 'Live demonstrations of the latest robot prototypes.'),
('Halloween Costume Contest', 'Red Square', '2025-10-31', '12:00', '13:00', 'ASUW', 'Show off your costume and win prizes for creativity.');

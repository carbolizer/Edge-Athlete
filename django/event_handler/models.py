"""
*** IMPORTANT ***
If you change models.py:
1. docker exec -it edgeathlete-django python manage.py makemigrations event_handler
2. docker exec -it edgeathlete-django python manage.py migrate
3. docker cp <container_path>/migrations/<file>.py ./django/event_handler/migrations/ (usually 'backend_container/' for us)
4. git add + commit the migration file

models.py — Database Table Definitions
----------------------------------------
Models are Python classes that define your database tables.
Each class is one table. Each attribute is one column.
Django automatically creates and manages the actual database tables
based on what you define here.

What it does:
  Defines the MotionEvent model which stores every motion detection
  event received from an ESP32 node.

Works with:
  - django migrations — every change here generates a migration file
  - event_handler/views.py — views create and query MotionEvent records
  - event_handler/admin.py — registers this model in the Django admin panel
  - PostgreSQL — Django translates these classes into actual database tables

For more information see
https://docs.djangoproject.com/en/5.1/topics/db/models/
"""
from django.db import models

class Device(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_ACTIVE = 'active'
    STATUS_DISABLED = 'disabled'
    STATUS_REMOVED = 'removed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_ACTIVE, 'Active'),
        (STATUS_DISABLED, 'Disabled'),
        (STATUS_REMOVED, 'Removed'),
    ]

    node_id = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255)
    location = models.CharField(max_length=255, null=True, blank=True)
    registered_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    is_active = models.BooleanField(default=True)
    
    # Latest device status from the most recent payload
    battery = models.IntegerField(null=True, blank=True)
    firmware_version = models.CharField(max_length=50, null=True, blank=True)
    signal_strength = models.IntegerField(null=True, blank=True)
    connection_interrupted = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} ({self.node_id})"


class MotionEvent(models.Model):
    # The specific ID provided by the sensor
    event_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    
    # Existing relationships
    device = models.ForeignKey(Device, on_delete=models.CASCADE, null=True, blank=True)
    node_id = models.CharField(max_length=255)
    location = models.CharField(max_length=255, null=True, blank=True)
    
    # Event specifics
    event_type = models.CharField(max_length=100, default='motion')
    motion = models.BooleanField(default=True)
    
    # Timing data
    # sensor_timestamp is when the ESP32 logged it, detected_at is when Django received it
    sensor_timestamp = models.DateTimeField(null=True, blank=True) 
    timezone = models.CharField(max_length=50, null=True, blank=True)
    detected_at = models.DateTimeField(auto_now_add=True) 
    
    # Point-in-time telemetry (what the battery/signal was during this specific event)
    battery_at_event = models.IntegerField(null=True, blank=True)
    signal_strength_at_event = models.IntegerField(null=True, blank=True)

    def __str__(self):
        # Controls how this object displays in the Django admin panel
        return f"{self.node_id} - {self.detected_at}"
    
    

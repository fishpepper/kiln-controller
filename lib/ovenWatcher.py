import threading,logging,json,time,datetime
import config
from oven import Oven
log = logging.getLogger(__name__)

class MQTTPublisher:
    def __init__(self, host, port, base_topic):
        import paho.mqtt.client as mqtt
        self.base_topic = base_topic
        self.client = mqtt.Client()
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.connected = False
        self.client.loop_start()
        log.info("MQTT connecting to %s:%d, base_topic=%s" % (host, port, base_topic))
        retries = 5
        for attempt in range(1, retries + 1):
            try:
                self.client.connect(host, port)
                return
            except Exception as e:
                log.error("MQTT connection attempt %d/%d failed: %s" % (attempt, retries, e))
                if attempt < retries:
                    time.sleep(5)
        log.error("MQTT could not connect after %d attempts, will keep retrying in background" % retries)

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            log.info("MQTT connected to broker")
        else:
            log.error("MQTT connection refused, rc=%d" % rc)

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        if rc != 0:
            log.warning("MQTT unexpected disconnect, will auto-reconnect")

    def publish(self, topic, value):
        """Generic publish to any topic. Use this for future extensibility."""
        log.info("MQTT publish %s = %s" % (topic, value))
        try:
            self.client.publish(topic, payload=str(value), qos=0)
        except Exception as e:
            log.error("MQTT publish error: %s" % e)

    def publish_state(self, state):
        """Publish configured fields from oven state to sub-topics.
        Derives on/off/power/temp from raw state and pidstats."""
        pidstats = state.get('pidstats', {})
        power = pidstats.get('out', 0.0) if pidstats else 0.0
        time_step = config.sensor_time_wait

        field_map = {
            'target': float(state.get('target', 0)),
            'temp': float(state.get('temperature', 0)),
            'power': float(power),
            'on': float(time_step * power),
            'off': float(time_step * (1 - power)),
        }

        for field in config.mqtt_fields:
            if field in field_map:
                self.publish("%s/%s" % (self.base_topic, field), f"{field_map[field]:.2f}")

    def publish_meter(self, meter, meter_data):
        """Publish SDM72 meter data to MQTT with register-aware formatting."""
        for k, v in meter_data.items():
            self.publish("%s/%s" % (config.mqtt_powermeter_topic, k), f"{v:.2f}")

class OvenWatcher(threading.Thread):
    def __init__(self,oven):
        self.last_profile = None
        self.last_log = []
        self.started = None
        self.recording = False
        self.observers = []
        self.mqtt = None
        if config.mqtt_enabled:
            self.mqtt = MQTTPublisher(config.mqtt_host, config.mqtt_port, config.mqtt_base_topic)
        threading.Thread.__init__(self)
        self.daemon = True
        self.oven = oven
        self.start()

# FIXME - need to save runs of schedules in near-real-time
# FIXME - this will enable re-start in case of power outage
# FIXME - re-start also requires safety start (pausing at the beginning
# until a temp is reached)
# FIXME - re-start requires a time setting in minutes.  if power has been
# out more than N minutes, don't restart
# FIXME - this should not be done in the Watcher, but in the Oven class

    def run(self):
        while True:
            oven_state = self.oven.get_state()
           
            # record state for any new clients that join
            if oven_state.get("state") == "RUNNING":
                self.last_log.append(oven_state)
            else:
                self.recording = False
            self.notify_all(oven_state)
            if self.mqtt:
                self.mqtt.publish_state(oven_state)
                if config.modbus_meter_enabled:
                    meter_data = self.oven.board.read_meter()
                    if meter_data:
                        self.mqtt.publish_meter(self.oven.board.meter, meter_data)
            time.sleep(self.oven.time_step)

    def lastlog_subset(self,maxpts=50):
        '''send about maxpts from lastlog by skipping unwanted data'''
        totalpts = len(self.last_log)
        if (totalpts <= maxpts):
            return self.last_log
        every_nth = int(totalpts / (maxpts - 1))
        return self.last_log[::every_nth]

    def record(self, profile):
        self.last_profile = profile
        self.last_log = []
        self.started = datetime.datetime.now()
        self.recording = True
        #we just turned on, add first state for nice graph
        self.last_log.append(self.oven.get_state())

    def add_observer(self,observer):
        if self.last_profile:
            p = {
                "name": self.last_profile.name,
                "data": self.last_profile.data, 
                "type" : "profile"
            }
        else:
            p = None
        
        backlog = {
            'type': "backlog",
            'profile': p,
            'log': self.lastlog_subset(),
            #'started': self.started
        }
        print(backlog)
        backlog_json = json.dumps(backlog)
        try:
            print(backlog_json)
            observer.send(backlog_json)
        except:
            log.error("Could not send backlog to new observer")
        
        self.observers.append(observer)

    def notify_all(self,message):
        message_json = json.dumps(message)
        log.debug("sending to %d clients: %s"%(len(self.observers),message_json))

        for wsock in self.observers:
            if wsock:
                try:
                    wsock.send(message_json)
                except:
                    log.error("could not write to socket %s"%wsock)
                    self.observers.remove(wsock)
            else:
                self.observers.remove(wsock)

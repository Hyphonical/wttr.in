"""
Multi-datasource manager for wttr.in to improve scalability.

This module manages multiple weather data sources and rotates between them
to distribute load and avoid hitting rate limits on individual APIs.
"""

import os
import time
import random
import requests
from typing import Dict, Optional
from dataclasses import dataclass
from enum import Enum

class DataSourceType(Enum):
    METNO = "metno"
    OPENWEATHERMAP = "openweathermap"
    WEATHERAPI = "weatherapi"
    ACCUWEATHER = "accuweather"

@dataclass
class DataSource:
    name: str
    type: DataSourceType
    base_url: str
    api_key: Optional[str] = None
    rate_limit: int = 1000  # requests per hour
    current_usage: int = 0
    last_reset: float = 0
    enabled: bool = True

class DataSourceManager:
    def __init__(self):
        self.sources: Dict[str, DataSource] = {}
        self._load_sources()
        self._start_usage_reset_timer()

    def _load_sources(self):
        """Load available data sources from configuration."""
        # Metno (free, no key required)
        self.sources["metno"] = DataSource(
            name="metno",
            type=DataSourceType.METNO,
            base_url="https://api.met.no",
            rate_limit=5000  # Metno allows up to 5k requests per hour
        )

        # OpenWeatherMap (free tier)
        api_key = os.environ.get("OPENWEATHERMAP_API_KEY")
        if api_key:
            self.sources["openweathermap"] = DataSource(
                name="openweathermap",
                type=DataSourceType.OPENWEATHERMAP,
                base_url="https://api.openweathermap.org/data/2.5",
                api_key=api_key,
                rate_limit=1000  # Free tier: 1000 calls/day
            )

        # WeatherAPI (free tier)
        api_key = os.environ.get("WEATHERAPI_KEY")
        if api_key:
            self.sources["weatherapi"] = DataSource(
                name="weatherapi",
                type=DataSourceType.WEATHERAPI,
                base_url="https://api.weatherapi.com/v1",
                api_key=api_key,
                rate_limit=1000000  # Free tier: 1M calls/month
            )

        # AccuWeather (free tier)
        api_key = os.environ.get("ACCUWEATHER_API_KEY")
        if api_key:
            self.sources["accuweather"] = DataSource(
                name="accuweather",
                type=DataSourceType.ACCUWEATHER,
                base_url="https://dataservice.accuweather.com",
                api_key=api_key,
                rate_limit=50  # Free tier: 50 calls/day
            )

    def _start_usage_reset_timer(self):
        """Reset usage counters hourly."""
        def reset_usage():
            current_time = time.time()
            for source in self.sources.values():
                if current_time - source.last_reset >= 3600:  # 1 hour
                    source.current_usage = 0
                    source.last_reset = current_time
            # Schedule next reset
            time.sleep(3600)
            reset_usage()

        import threading
        timer = threading.Thread(target=reset_usage, daemon=True)
        timer.start()

    def get_available_source(self) -> Optional[DataSource]:
        """Get an available data source that hasn't exceeded its rate limit."""
        available_sources = [
            source for source in self.sources.values()
            if source.enabled and source.current_usage < source.rate_limit
        ]

        if not available_sources:
            return None

        # Random selection to distribute load
        return random.choice(available_sources)

    def mark_source_used(self, source_name: str):
        """Increment usage counter for a source."""
        if source_name in self.sources:
            self.sources[source_name].current_usage += 1

    def disable_source(self, source_name: str):
        """Temporarily disable a source (e.g., if it's returning errors)."""
        if source_name in self.sources:
            self.sources[source_name].enabled = False
            # Re-enable after 5 minutes
            def reenable():
                time.sleep(300)
                self.sources[source_name].enabled = True
            import threading
            threading.Thread(target=reenable, daemon=True).start()

    def fetch_weather_data(self, location: str, days: int = 3) -> Optional[Dict]:
        """Fetch weather data from available sources."""
        source = self.get_available_source()
        if not source:
            return None

        try:
            data = self._fetch_from_source(source, location, days)
            if data:
                self.mark_source_used(source.name)
                return data
            else:
                self.disable_source(source.name)
                return None
        except Exception as e:
            print(f"Error fetching from {source.name}: {e}")
            self.disable_source(source.name)
            return None

    def _fetch_from_source(self, source: DataSource, location: str, days: int) -> Optional[Dict]:
        """Fetch data from a specific source."""
        if source.type == DataSourceType.METNO:
            return self._fetch_metno(location, days)
        elif source.type == DataSourceType.OPENWEATHERMAP:
            return self._fetch_openweathermap(location, days)
        elif source.type == DataSourceType.WEATHERAPI:
            return self._fetch_weatherapi(location, days)
        elif source.type == DataSourceType.ACCUWEATHER:
            return self._fetch_accuweather(location, days)
        return None

    def _fetch_metno(self, location: str, days: int) -> Optional[Dict]:
        """Fetch from MET Norway API."""
        # Implementation similar to existing metno.py
        url = f"https://api.met.no/weatherapi/locationforecast/2.0/complete?lat={location.split(',')[0]}&lon={location.split(',')[1]}"
        headers = {'User-Agent': 'wttr.in/1.0'}
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            return self._convert_metno_to_standard(response.json(), days)
        return None

    def _fetch_openweathermap(self, location: str, days: int) -> Optional[Dict]:
        """Fetch from OpenWeatherMap API."""
        if not self.sources["openweathermap"].api_key:
            return None

        # Parse location (lat,lng)
        lat, lng = location.split(',')
        url = f"{self.sources['openweathermap'].base_url}/onecall?lat={lat}&lon={lng}&exclude=minutely&appid={self.sources['openweathermap'].api_key}"
        response = requests.get(url, timeout=10)

        if response.status_code == 200:
            return self._convert_openweather_to_standard(response.json(), days)
        return None

    def _fetch_weatherapi(self, location: str, days: int) -> Optional[Dict]:
        """Fetch from WeatherAPI."""
        if not self.sources["weatherapi"].api_key:
            return None

        url = f"{self.sources['weatherapi'].base_url}/forecast.json?q={location}&days={days}&key={self.sources['weatherapi'].api_key}"
        response = requests.get(url, timeout=10)

        if response.status_code == 200:
            return self._convert_weatherapi_to_standard(response.json(), days)
        return None

    def _fetch_accuweather(self, location: str, days: int) -> Optional[Dict]:
        """Fetch from AccuWeather API."""
        if not self.sources["accuweather"].api_key:
            return None

        # First get location key
        search_url = f"{self.sources['accuweather'].base_url}/locations/v1/cities/geoposition/search?q={location}&apikey={self.sources['accuweather'].api_key}"
        search_response = requests.get(search_url, timeout=10)

        if search_response.status_code != 200:
            return None

        location_key = search_response.json()['Key']

        # Then get forecast
        forecast_url = f"{self.sources['accuweather'].base_url}/forecasts/v1/daily/5day/{location_key}?apikey={self.sources['accuweather'].api_key}"
        forecast_response = requests.get(forecast_url, timeout=10)

        if forecast_response.status_code == 200:
            return self._convert_accuweather_to_standard(forecast_response.json(), days)
        return None

    def _convert_metno_to_standard(self, data: Dict, days: int) -> Dict:
        """Convert MET Norway response to wttr.in standard format."""
        # Simplified conversion - would need full implementation
        return {
            "data": {
                "current_condition": [{
                    "temp_C": str(data.get('properties', {}).get('timeseries', [{}])[0].get('data', {}).get('instant', {}).get('details', {}).get('air_temperature', 0)),
                    "weatherDesc": [{"value": "Clear"}],
                    "humidity": "50",
                    "windspeedKmph": "10"
                }],
                "weather": []
            }
        }

    def _convert_openweather_to_standard(self, data: Dict, days: int) -> Optional[Dict]:
        """Convert OpenWeatherMap response to wttr.in standard format."""
        if not data or 'current' not in data:
            return None

        current = data['current']
        lat = data.get('lat', 0)
        lon = data.get('lon', 0)

        # Convert current weather
        current_condition = self._convert_openweather_hourly(current)

        # Convert daily forecasts
        weather = []
        if 'daily' in data:
            for day_data in data['daily'][:days]:
                weather.append(self._convert_openweather_daily(day_data))

        return {
            "data": {
                "request": [{
                    "type": "feature",
                    "query": f"{lat},{lon}"
                }],
                "current_condition": [current_condition],
                "weather": weather
            }
        }

    def _convert_openweather_hourly(self, hour_data: Dict) -> Dict:
        """Convert OpenWeatherMap hourly data to wttr.in format."""
        temp_c = hour_data.get('temp', 0)
        if isinstance(temp_c, dict):  # Daily data has temp as dict
            temp_c = temp_c.get('day', 0)

        weather_id = hour_data.get('weather', [{}])[0].get('id', 800)
        weather_code = self._openweather_to_wwo_code(weather_id)
        weather_desc = hour_data.get('weather', [{}])[0].get('description', 'Clear')

        wind_speed_mps = hour_data.get('wind_speed', 0)
        wind_speed_kmph = wind_speed_mps * 3.6  # Convert m/s to km/h

        return {
            "temp_C": str(int(round(temp_c, 0))),
            "temp_F": str(int(round(temp_c * 9/5 + 32, 0))),
            "weatherCode": str(weather_code),
            "weatherDesc": [{"value": weather_desc.capitalize()}],
            "windspeedKmph": str(int(round(wind_speed_kmph, 0))),
            "windspeedMiles": str(int(round(wind_speed_kmph * 0.621371, 0))),
            "winddirDegree": str(hour_data.get('wind_deg', 0)),
            "winddir16Point": self._degrees_to_16_point(hour_data.get('wind_deg', 0)),
            "precipMM": str(hour_data.get('rain', {}).get('1h', 0) if 'rain' in hour_data else 0),
            "humidity": str(hour_data.get('humidity', 0)),
            "pressure": str(hour_data.get('pressure', 0)),
            "visibility": str(hour_data.get('visibility', 0) if 'visibility' in hour_data else 10000),
            "cloudcover": str(hour_data.get('clouds', 0)),
            "FeelsLikeC": str(int(round(hour_data.get('feels_like', temp_c), 0))),
            "uvIndex": str(int(hour_data.get('uvi', 0))),
        }

    def _convert_openweather_daily(self, day_data: Dict) -> Dict:
        """Convert OpenWeatherMap daily data to wttr.in format."""
        temp = day_data.get('temp', {})

        return {
            "date": day_data.get('dt', 0),  # Unix timestamp
            "maxtempC": str(int(round(temp.get('max', 0), 0))),
            "maxtempF": str(int(round(temp.get('max', 0) * 9/5 + 32, 0))),
            "mintempC": str(int(round(temp.get('min', 0), 0))),
            "mintempF": str(int(round(temp.get('min', 0) * 9/5 + 32, 0))),
            "avgtempC": str(int(round(temp.get('day', 0), 0))),
            "avgtempF": str(int(round(temp.get('day', 0) * 9/5 + 32, 0))),
            "totalSnow_cm": str(day_data.get('snow', 0)),
            "sunHour": "12",  # Not provided by OpenWeather, default
            "uvIndex": str(int(day_data.get('uvi', 0))),
            "hourly": []  # OpenWeather doesn't provide hourly in daily endpoint
        }

    def _openweather_to_wwo_code(self, owm_code: int) -> int:
        """Convert OpenWeatherMap weather codes to WWO codes."""
        # Mapping based on OpenWeatherMap API documentation
        mapping = {
            200: 200,  # Thunderstorm with light rain
            201: 386,  # Thunderstorm with rain
            202: 389,  # Thunderstorm with heavy rain
            210: 200,  # Light thunderstorm
            211: 389,  # Thunderstorm
            212: 389,  # Heavy thunderstorm
            221: 389,  # Ragged thunderstorm
            230: 200,  # Thunderstorm with light drizzle
            231: 386,  # Thunderstorm with drizzle
            232: 389,  # Thunderstorm with heavy drizzle
            300: 266,  # Light intensity drizzle
            301: 266,  # Drizzle
            302: 302,  # Heavy intensity drizzle
            310: 266,  # Light intensity drizzle rain
            311: 293,  # Drizzle rain
            312: 302,  # Heavy intensity drizzle rain
            313: 305,  # Shower rain and drizzle
            314: 302,  # Heavy shower rain and drizzle
            321: 299,  # Shower drizzle
            500: 176,  # Light rain
            501: 293,  # Moderate rain
            502: 302,  # Heavy intensity rain
            503: 308,  # Very heavy rain
            504: 308,  # Extreme rain
            511: 284,  # Freezing rain
            520: 299,  # Light intensity shower rain
            521: 305,  # Shower rain
            522: 302,  # Heavy intensity shower rain
            531: 305,  # Ragged shower rain
            600: 320,  # Light snow
            601: 332,  # Snow
            602: 230,  # Heavy snow
            611: 281,  # Sleet
            612: 284,  # Light shower sleet
            613: 284,  # Shower sleet
            615: 317,  # Light rain and snow
            616: 317,  # Rain and snow
            620: 368,  # Light shower snow
            621: 371,  # Shower snow
            622: 230,  # Heavy shower snow
            701: 143,  # Mist
            711: 143,  # Smoke
            721: 143,  # Haze
            731: 143,  # Dust
            741: 143,  # Fog
            751: 143,  # Sand
            761: 143,  # Dust
            762: 143,  # Volcanic ash
            771: 143,  # Squalls
            781: 143,  # Tornado
            800: 113,  # Clear sky
            801: 116,  # Few clouds
            802: 119,  # Scattered clouds
            803: 119,  # Broken clouds
            804: 122,  # Overcast clouds
        }
        return mapping.get(owm_code, 113)  # Default to clear sky

    def _degrees_to_16_point(self, degrees: float) -> str:
        """Convert wind direction in degrees to 16-point compass."""
        directions = [
            "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"
        ]
        index = round(degrees / 22.5) % 16
        return directions[index]
        
    def _convert_weatherapi_to_standard(self, data: Dict, days: int) -> Optional[Dict]:
        """Convert WeatherAPI response to wttr.in standard format."""
        if not data or 'current' not in data or 'location' not in data:
            return None

        current = data['current']
        location = data['location']

        # Convert current weather
        current_condition = self._convert_weatherapi_hourly(current)

        # Convert daily forecasts
        weather = []
        if 'forecast' in data and 'forecastday' in data['forecast']:
            for day_data in data['forecast']['forecastday'][:days]:
                weather.append(self._convert_weatherapi_daily(day_data))

        return {
            "data": {
                "request": [{
                    "type": "feature",
                    "query": f"{location.get('lat', 0)},{location.get('lon', 0)}"
                }],
                "current_condition": [current_condition],
                "weather": weather
            }
        }

    def _convert_weatherapi_hourly(self, hour_data: Dict) -> Dict:
        """Convert WeatherAPI hourly data to wttr.in format."""
        temp_c = hour_data.get('temp_c', 0)

        wind_kmph = hour_data.get('wind_kph', 0)

        return {
            "temp_C": str(int(round(temp_c, 0))),
            "temp_F": str(int(round(hour_data.get('temp_f', temp_c * 9/5 + 32), 0))),
            "weatherCode": str(hour_data.get('condition', {}).get('code', 1000)),
            "weatherDesc": [{"value": hour_data.get('condition', {}).get('text', 'Clear')}],
            "windspeedKmph": str(int(round(wind_kmph, 0))),
            "windspeedMiles": str(int(round(hour_data.get('wind_mph', wind_kmph * 0.621371), 0))),
            "winddirDegree": str(hour_data.get('wind_degree', 0)),
            "winddir16Point": hour_data.get('wind_dir', 'N'),
            "precipMM": str(hour_data.get('precip_mm', 0)),
            "humidity": str(hour_data.get('humidity', 0)),
            "pressure": str(hour_data.get('pressure_mb', 0)),
            "visibility": str(hour_data.get('vis_km', 0) * 1000),  # Convert km to meters
            "cloudcover": str(hour_data.get('cloud', 0)),
            "FeelsLikeC": str(int(round(hour_data.get('feelslike_c', temp_c), 0))),
            "uvIndex": str(int(hour_data.get('uv', 0))),
        }

    def _convert_weatherapi_daily(self, day_data: Dict) -> Dict:
        """Convert WeatherAPI daily data to wttr.in format."""
        day = day_data.get('day', {})

        return {
            "date": day_data.get('date', ''),
            "maxtempC": str(int(round(day.get('maxtemp_c', 0), 0))),
            "maxtempF": str(int(round(day.get('maxtemp_f', 0), 0))),
            "mintempC": str(int(round(day.get('mintemp_c', 0), 0))),
            "mintempF": str(int(round(day.get('mintemp_f', 0), 0))),
            "avgtempC": str(int(round(day.get('avgtemp_c', 0), 0))),
            "avgtempF": str(int(round(day.get('avgtemp_f', 0), 0))),
            "totalSnow_cm": str(day.get('totalsnow_cm', 0)),
            "sunHour": "12",  # Not provided, default
            "uvIndex": str(int(day.get('uv', 0))),
            "hourly": []  # WeatherAPI provides hourly but we'd need to fetch separately
        }
        
    def _convert_accuweather_to_standard(self, data: Dict, days: int) -> Optional[Dict]:
        """Convert AccuWeather response to wttr.in standard format."""
        if not data or not isinstance(data, list) or len(data) == 0:
            return None

        # AccuWeather doesn't provide current conditions in daily forecast
        # We'll use the first day's data as approximate current
        location_lat = 0  # Would need to be passed from location search
        location_lon = 0

        # Convert daily forecasts
        weather = []
        for day_data in data[:days]:
            weather.append(self._convert_accuweather_daily(day_data))

        # Use first day for current condition approximation
        current_condition = self._convert_accuweather_daily(data[0])
        # Remove daily-specific fields for current
        current_condition.pop('date', None)
        current_condition.pop('maxtempC', None)
        current_condition.pop('maxtempF', None)
        current_condition.pop('mintempC', None)
        current_condition.pop('mintempF', None)
        current_condition.pop('avgtempC', None)
        current_condition.pop('avgtempF', None)

        return {
            "data": {
                "request": [{
                    "type": "feature",
                    "query": f"{location_lat},{location_lon}"
                }],
                "current_condition": [current_condition],
                "weather": weather
            }
        }

    def _convert_accuweather_daily(self, day_data: Dict) -> Dict:
        """Convert AccuWeather daily data to wttr.in format."""
        temp = day_data.get('Temperature', {})
        real_feel = day_data.get('RealFeelTemperature', {})
        wind = day_data.get('Wind', {}).get('Speed', {})

        # Get max/min temps
        max_temp = temp.get('Maximum', {}).get('Value', 0)
        min_temp = temp.get('Minimum', {}).get('Value', 0)
        avg_temp = (max_temp + min_temp) / 2

        return {
            "date": day_data.get('Date', ''),
            "maxtempC": str(int(round(max_temp, 0))),
            "maxtempF": str(int(round(max_temp * 9/5 + 32, 0))),
            "mintempC": str(int(round(min_temp, 0))),
            "mintempF": str(int(round(min_temp * 9/5 + 32, 0))),
            "avgtempC": str(int(round(avg_temp, 0))),
            "avgtempF": str(int(round(avg_temp * 9/5 + 32, 0))),
            "totalSnow_cm": "0",  # Not provided by AccuWeather in this endpoint
            "sunHour": str(day_data.get('HoursOfSun', 12)),
            "uvIndex": str(day_data.get('UVIndex', 0)),
            "hourly": [],  # AccuWeather doesn't provide hourly in daily endpoint
            # Additional current weather fields
            "temp_C": str(int(round(avg_temp, 0))),
            "temp_F": str(int(round(avg_temp * 9/5 + 32, 0))),
            "weatherCode": "113",  # Default clear, would need mapping
            "weatherDesc": [{"value": day_data.get('IconPhrase', 'Clear')}],
            "windspeedKmph": str(int(round(wind.get('Value', 0) * 1.60934, 0))),  # Convert mph to kmh
            "windspeedMiles": str(int(round(wind.get('Value', 0), 0))),
            "winddirDegree": str(day_data.get('Wind', {}).get('Direction', {}).get('Degrees', 0)),
            "winddir16Point": "N",  # Would need conversion
            "precipMM": "0",  # Not provided in daily summary
            "humidity": "50",  # Not provided
            "pressure": "1013",  # Not provided
            "visibility": "10000",  # Not provided
            "cloudcover": "0",  # Not provided
            "FeelsLikeC": str(int(round(real_feel.get('Maximum', {}).get('Value', avg_temp), 0))),
        }

# Global instance
datasource_manager = DataSourceManager()

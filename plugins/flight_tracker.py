import time
import logging
import requests
from core.message import Message
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

_command = ["flight", "航班", "shairport"]
_name = "实时航班查询"
_man = """实时航班查询（数据源: FlightRadar24）。
用法: {0} <航班号>
例如: {0} MU737
例如: {0} CA992
例如: {0} CZ378
"""
_tool_description = (
    "实时航班查询工具。参数(query)传入航班号（如 MU737、CA992、CZ378）。"
    "返回航班实时状态：出发/到达机场、计划/实际/预计起降时间、当前高度速度坐标、延误信息。"
    "仅能查询当前正在飞行或当日有计划的航班。"
)
_enabled = 1


# ICAO airline codes for Chinese carriers (most common)
_AIRLINE_ICAO_MAP = {
    "CA": "CCA",  # Air China
    "MU": "CES",  # China Eastern
    "CZ": "CSN",  # China Southern
    "HU": "CHH",  # Hainan Airlines
    "ZH": "CSZ",  # Shenzhen Airlines
    "FM": "CSH",  # Shanghai Airlines
    "SC": "CDG",  # Shandong Airlines
    "3U": "CSC",  # Sichuan Airlines
    "MF": "CXA",  # Xiamen Airlines
    "GJ": "CDC",  # Loong Air
    "HO": "DKH",  # Juneyao Airlines
    "9C": "CQH",  # Spring Airlines
    "TV": "TSC",  # Tibet Airlines (now Xizang Airlines)
    "GS": "GCR",  # Tianjin Airlines
    "JD": "CBJ",  # Capital Airlines
    "KN": "CUN",  # China United Airlines
    "PN": "CHB",  # West Air
    # International
    "AA": "AAL",  # American Airlines
    "UA": "UAL",  # United Airlines
    "DL": "DAL",  # Delta Air Lines
    "BA": "BAW",  # British Airways
    "LH": "DLH",  # Lufthansa
    "AF": "AFR",  # Air France
    "NH": "ANA",  # ANA
    "JL": "JAL",  # Japan Airlines
    "SQ": "SIA",  # Singapore Airlines
    "CX": "CPA",  # Cathay Pacific
    "QF": "QFA",  # Qantas
    "EK": "UAE",  # Emirates
    "TK": "THY",  # Turkish Airlines
    "KE": "KAL",  # Korean Air
    "OZ": "AAR",  # Asiana Airlines
    "BR": "EVA",  # EVA Air
    "CI": "CAL",  # China Airlines (Taiwan)
    "TR": "TGW",  # Scoot
    "QR": "QTR",  # Qatar Airways
    "EY": "ETD",  # Etihad
    "SU": "AFL",  # Aeroflot
}


def _extract_airline_icao(flight_number: str) -> str | None:
    """Extract IATA airline code from flight number and map to ICAO."""
    flight_number = flight_number.upper().strip()
    # Try 2-char prefix first (e.g. MU, CA, CZ, 3U, 9C)
    for length in (2, 3):
        prefix = flight_number[:length]
        if prefix in _AIRLINE_ICAO_MAP:
            return _AIRLINE_ICAO_MAP[prefix]
    return None


def _format_time(ts: int | None, utc_offset: int = 8) -> str:
    """Format a UNIX timestamp to a readable local time string (default: UTC+8)."""
    if not ts:
        return "N/A"
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts + utc_offset * 3600))


def _query_flight(flight_number: str) -> str:
    """Query FlightRadar24 for a specific flight number."""
    from FlightRadarAPI import FlightRadar24API

    flight_number = flight_number.upper().strip()
    fr = FlightRadar24API()

    airline_icao = _extract_airline_icao(flight_number)
    if not airline_icao:
        return f"404: nemo: 无法识别航班号 {flight_number} 的航空公司代码。"

    # Get all flights for this airline
    try:
        flights = fr.get_flights(airline=airline_icao)
    except Exception as e:
        logger.warning("FlightRadar24 get_flights failed: %s", e)
        return f"502: nemo: FlightRadar24 查询失败: {e}"

    if not flights:
        return f"404: nemo: 航空公司 {airline_icao} 当前没有在飞航班（可能暂时被限流，请稍后重试）。"

    # Find matching flight
    target = None
    for f in flights:
        fn = (f.number or "").upper().replace(" ", "")
        cs = (f.callsign or "").upper()
        if fn == flight_number or cs == airline_icao + flight_number[2:]:
            target = f
            break

    if not target:
        return (
            f"404: nemo: 未找到航班 {flight_number}。"
            f"该航班可能尚未起飞、已降落或今日无计划。"
            f"（当前该航司有 {len(flights)} 架在飞航班）"
        )

    # Get detailed info
    try:
        details = fr.get_flight_details(target)
    except Exception as e:
        logger.warning("FlightRadar24 get_flight_details failed: %s", e)
        details = {}

    # Build response
    lines = [f"✈️ 航班 {flight_number}"]

    # Aircraft info
    ac = details.get("aircraft", {})
    ac_model = ac.get("model", {}).get("text") or target.aircraft_code or "N/A"
    ac_reg = ac.get("registration") or target.registration or "N/A"
    lines.append(f"机型: {ac_model} | 注册号: {ac_reg}")

    # Airline
    al = details.get("airline", {})
    airline_name = al.get("name") or airline_icao
    lines.append(f"航空公司: {airline_name}")

    # Airports
    apt = details.get("airport", {})
    origin = apt.get("origin", {})
    dest = apt.get("destination", {})
    origin_name = origin.get("name") or target.origin_airport_iata or "N/A"
    origin_iata = origin.get("code", {}).get("iata") or target.origin_airport_iata or ""
    dest_name = dest.get("name") or target.destination_airport_iata or "N/A"
    dest_iata = dest.get("code", {}).get("iata") or target.destination_airport_iata or ""
    lines.append(f"出发: {origin_name} ({origin_iata})")
    lines.append(f"到达: {dest_name} ({dest_iata})")

    # Times
    t = details.get("time", {})
    sched = t.get("scheduled", {})
    real = t.get("real", {})
    est = t.get("estimated", {})

    dep_sched = _format_time(sched.get("departure"))
    arr_sched = _format_time(sched.get("arrival"))
    dep_real = _format_time(real.get("departure"))
    arr_real = _format_time(real.get("arrival"))
    arr_est = _format_time(est.get("arrival"))

    lines.append(f"计划起飞: {dep_sched}")
    if dep_real != "N/A":
        lines.append(f"实际起飞: {dep_real}")
    lines.append(f"计划到达: {arr_sched}")
    if arr_est != "N/A":
        lines.append(f"预计到达: {arr_est}")
    if arr_real != "N/A":
        lines.append(f"实际到达: {arr_real}")

    # Status
    status = details.get("status", {})
    status_text = status.get("text") or ("在飞" if not target.on_ground else "地面")
    lines.append(f"状态: {status_text}")

    # Live position
    if not target.on_ground and target.altitude > 0:
        lines.append(
            f"当前位置: ({target.latitude:.2f}, {target.longitude:.2f}) "
            f"| 高度: {target.altitude}ft "
            f"| 速度: {target.ground_speed}kt "
            f"| 航向: {target.heading}°"
        )

    # Delay info
    hist = t.get("historical", {})
    delay = hist.get("delay")
    if delay:
        try:
            delay_sec = int(delay)
            if delay_sec > 0:
                lines.append(f"⚠️ 延误: {delay_sec // 60} 分钟")
            elif delay_sec < 0:
                lines.append(f"✅ 提前: {abs(delay_sec) // 60} 分钟")
        except (ValueError, TypeError):
            pass

    return "\n".join(lines)


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    query = message.request.args.strip()
    if not query:
        message.reply("请输入航班号，例如: flight MU737")
        return

    result = _query_flight(query)
    message.reply(result)

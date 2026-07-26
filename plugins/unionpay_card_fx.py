import requests
from datetime import datetime, timedelta

TEMPLATE = "https://www.unionpayintl.com/upload/jfimg/{}.json"


def get_unionpay_card_fx(src: str, dst: str = "CNY") -> tuple[float, str, str]:
    """
    src: source currency
    dst: destination currency
    return: (rate, timestamp, comment)
    """
    src = src.upper()
    dst = dst.upper()
    current_date = datetime.now()
    current_date_str = current_date.strftime("%Y%m%d")
    url = TEMPLATE.format(current_date_str)
    comment = ""
    response = requests.get(url)
    while response.status_code != 200:
        comment = "!非最新汇率"
        current_date = current_date - timedelta(days=1)
        current_date_str = current_date.strftime("%Y%m%d")
        url = TEMPLATE.format(current_date_str)
        response = requests.get(url)
    """
    {
        "exchangeRateJson": [
            {
            "transCur": "AED",
            "baseCur": "AUD",
            "rateData": 0.44094899
            },
            ...
        ],
        "curDate": "2025-01-04"
    }
    """

    data = response.json()
    for i in data["exchangeRateJson"]:
        if i["transCur"] == src and i["baseCur"] == dst:
            return (i["rateData"], data["curDate"], comment)
    return (0, "?", "?")

fx_code_to_name = {
    "USD": "U.S.Dollar",
    "AED": "U.A.E. Dirham",
    "AFN": "Afghani",
    "ALL": "Albanian Lek",
    "AMD": "Armenian Dram",
    "ANG": "Netherlands Antillian Guilder",
    "AOA": "Kwanza",
    "ARS": "Argentine Peso",
    "AUD": "Australian Dollar",
    "AWG": "Aruban Guilder",
    "AZN": "Azerbaijanian Manat",
    "BAM": "Convertible Mark",
    "BBD": "Barbados Dollar",
    "BDT": "Taka",
    "BGN": "Bulgarian Lev",
    "BHD": "Bahraini Dinar",
    "BIF": "Burundi Franc",
    "BMD": "Bermudian Dollar",
    "BND": "Brunei Dollar",
    "BOB": "Boliviano",
    "BRL": "Brazilian Real",
    "BSD": "Bahamian Dollar",
    "BTN": "Ngultrum",
    "BWP": "Pula",
    "BYN": "Belarusian Ruble",
    "BYR": "Belarussian Ruble",
    "BZD": "Belize Dollar",
    "CAD": "Canadian Dollar",
    "CDF": "Franc Congolais",
    "CHF": "Swiss Franc",
    "CLP": "Chilean Peso",
    "CNY": "Yuan Renminbi",
    "COP": "Colombian Peso",
    "CRC": "Costa Rican Colon",
    "CUC": "Cuban Conv Peso",
    "CVE": "Cape Verde Escudo",
    "CZK": "Czech Koruna",
    "DJF": "Djibouti Franc",
    "DKK": "Danish Krone",
    "DOP": "Dominican Peso",
    "DZD": "Algerian Dinar",
    "EGP": "Egyptian Pound",
    "ERN": "Nafka",
    "ETB": "Ethiopian Birr",
    "EUR": "Euro",
    "FJD": "Fiji Dollar",
    "FKP": "Falkland Islands Pound",
    "GBP": "Pound Sterling",
    "GEL": "Lari",
    "GHS": "Cedi",
    "GIP": "Gibraltar Pound",
    "GMD": "Dalasi",
    "GNF": "Guinea Franc",
    "GTQ": "Guatemala Quetzal",
    "GYD": "Guyanese Dollar",
    "HKD": "Hong Kong Dollar",
    "HNL": "Honduras Lempira",
    "HRK": "Croatia Kuna",
    "HTG": "Haitian Gourde",
    "HUF": "Forint",
    "IDR": "Rupiah",
    "ILS": "New Israeli Sheqel",
    "INR": "Indian Rupee",
    "IQD": "Iraqi Dinar",
    "IRR": "Iranian Rial",
    "ISK": "Iceland Krona",
    "JMD": "Jamaican Dollar",
    "JOD": "Jordanian Dinar",
    "JPY": "Yen",
    "KES": "Kenyan Shilling",
    "KGS": "Som",
    "KHR": "Cambodia Riel",
    "KMF": "Comoro Franc",
    "KRW": "Won",
    "KWD": "Kuwaiti Dinar",
    "KYD": "Cayman Islands Dollar",
    "KZT": "Tenge",
    "LAK": "Kip",
    "LBP": "Lebanese Pound",
    "LKR": "Sri Lanka Rupee",
    "LRD": "Liberian Dollar",
    "LSL": "Loti",
    "LTL": "Lithunianian Litas",
    "LYD": "Libyan Dinar",
    "MAD": "Moroccan Dirham",
    "MDL": "Moldovia Leu",
    "MGA": "Malagasy Ariary",
    "MKD": "Denar",
    "MMK": "Myanmar Kyat",
    "MNT": "Tugrik",
    "MOP": "Pataca",
    "MRO": "Ouguiya",
    "MRU": "Ouguiya(new)",
    "MUR": "Mauritius Rupee",
    "MVR": "Rufiyaa",
    "MWK": "Kwacha",
    "MXN": "Mexican Peso",
    "MYR": "Malaysian Ringgit",
    "MZN": "Metical",
    "NAD": "Dollar",
    "NGN": "Naira",
    "NIO": "Nicaragua Cordoba Oro",
    "NOK": "Norwegian Krone",
    "NPR": "Nepalese Rupee",
    "NZD": "New Zealand Dollar",
    "OMR": "Rial Omani",
    "PAB": "Panamanian Balboa",
    "PEN": "Nuevo Sol",
    "PGK": "Kina",
    "PHP": "Philippine Peso",
    "PKR": "Pakistan Rupee",
    "PLN": "Zloty",
    "PYG": "Paraguay Guarani",
    "QAR": "Qatari Rial",
    "RON": "LEU",
    "RSD": "Serbian Dinar",
    "RUB": "Russian Ruble",
    "RWF": "Rwanda Franc",
    "SAR": "Saudi Riyal",
    "SBD": "Solomon Islands Dollar",
    "SCR": "Seychelles Rupee",
    "SDG": "Sudanese Pound",
    "SEK": "Swedish Krona",
    "SGD": "Singapore Dollar",
    "SHP": "St. Helena Pound",
    "SLL": "Leone",
    "SOS": "Somalia Shilling",
    "SRD": "Suriname Dollar",
    "SSP": "South Sudanese Pound",
    "STD": "Dobra",
    "SVC": "El Salvador Colón",
    "SYP": "Syrian Pound",
    "SZL": "Lilangeni",
    "THB": "Baht",
    "TJS": "Somoni",
    "TMT": "New Manat",
    "TND": "Tunisian Dinar",
    "TOP": "Pa'anga",
    "TRY": "Turkish Lira",
    "TTD": "Trinidad and Tobago Dollar",
    "TWD": "New Taiwan Dollar",
    "TZS": "Tanzanian Shilling",
    "UAH": "Hryvnia",
    "UGX": "Uganda Shilling",
    "USD": "U.S.Dollar",
    "UYU": "Peso Uruguayo",
    "UZS": "Uzbekistan Sum",
    "VND": "Dong",
    "VUV": "Vatu",
    "WST": "Tala",
    "XAF": "CFA Franc BEAC",
    "XCD": "East Caribbean Dollar",
    "XOF": "CFA Franc BCEAO",
    "XPF": "CFP Franc",
    "YER": "Yemeni Rial",
    "ZAR": "South African Rand",
    "ZMW": "Zambian Kwacha",
    "ZWD": "Zimbabwe Dollar",
}


def unionpay_fx_code(src: str, dst: str = "CNY") -> tuple[str, str]:
    src = src.upper()
    dst = dst.upper()
    try:
        return (f"{src}, {fx_code_to_name[src]}", f"{dst}, {fx_code_to_name[dst]}")
    except KeyError:
        return f"{src}, {dst}"


def workload(src: str, dst: str = "CNY") -> str:
    src = src.upper()
    dst = dst.upper()
    tmp = get_unionpay_card_fx(src, dst)
    return f"1 {src} (交易币种) = {tmp[0]} {dst} (扣账币种) ({tmp[1]})" + (
        "" if tmp[2] == "" else f" {tmp[2]}"
    )


from classes.message import Message
from utilities import generic_exception_handler

import traceback

# _allowed_groups = ['485541033'] # uncomment to set allowed groups, superusers will always be allowed
# _allowed_users = ['1234567890'] # uncomment to set allowed users, superusers will always be allowed
# _disallowed_users = ['1234567890'] # uncomment to set disallowed users, superusers will always be allowed
# _disallowed_groups = ['485541033'] # uncomment to set disallowed groups, superusers will always be allowed

_command = ["unionpay_card_fx"]
_name = "银联卡汇率"
_man = """本系统中显示的汇率来源于银联系统。银联系统中的汇率，是依据多个渠道和市场化原则取得的基础汇率，不包括发卡行额外收取的任何费用以及四舍五入等因素的影响（如有）。
银联卡交易通常适用交易日当天的汇率，但在特殊情况下，适用交易结算日的汇率。（注：交易日系指交易实际发起的日期，结算日系指银联与发卡行、收单行进行资金清算的日期）
银联系统汇率周一至周五每日更新，周六周日延用周五汇率。如无特殊情况，部分欧系货币汇率生效时间为北京时间16:30，其他货币汇率生效时间为北京时间11:00。特别提示，本系统查询显示的汇率更新时间可能晚于前述生效时间。
您如需更详细地了解交易汇率，请咨询发卡行。
用法: {0} [货币代码]
如：{0} AUD
"""
_tool_description = (
    "查询银联卡境外消费的实时汇率。"
    "参数(query)传入三字母ISO货币代码，如 'USD', 'JPY', 'EUR', 'GBP', 'HKD'。"
    "如不传参，默认查USD。注意：仅支持3字母货币代码，不支持中文和数量。"
)


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    args = message.request.args.strip()
    # IF NEED ARGS
    if args == "":
        args = "USD"
    if len(args) != 3:
        message.reply(
            "400: nemo: 不像是一个合理的货币代码，注意这里不支持像汇率指令一样直接加数字在后面的用法。"
        )
        return
    result = workload(args)
    message.reply(result)


if __name__ == "__main__":
    import sys
    class MockRequest:
        def __init__(self, args):
            self.args = args
    class MockMessage:
        def __init__(self, args):
            self.request = MockRequest(args)
            self.replies = []
        def reply(self, text, **kwargs):
            print(f"[{__name__}] REPLY:", text)
            if kwargs:
                print(f"[{__name__}] KWARGS:", kwargs)
            self.replies.append(text)
            
    args = " ".join(sys.argv[1:])
    msg = MockMessage(args)
    print(f"Testing with args: '{args}'")
    bot_execute(msg, {})

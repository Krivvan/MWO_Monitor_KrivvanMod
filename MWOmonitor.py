APPNAME = 'MWO-Monitor'
APP_VERSION = 'v07g'
POLL_INTERVAL = 15 * 1000 #                     poll the web site for results every x secs
RESULT_POST_INTERVAL = 300 # poll other threads to post results every x ms
CSV_INTERVAL = 10 # save CSV every x games
LOGIN_THROTTLE = 30 # login attempts every x seconds max
UPDATE_URL = "http://goo.gl/2s6yr8" # software "repository"
DEFAULT_PASSWORD = "x"
EMAIL   = ''
PASS = ''
SCRNSHOTLOCATION = "C:/Program Files(x86)/Piranha Games/MechWarrior Online/USER/ScreenShots/"
SCRNSHOTDESTINATION = "C:/MWO_Monitor_Screenshots"

global DEV_MODE
DEV_MODE = False

# system stuff
#import time # for, well, timing things!
import os.path
from os import rename
from sys import argv
from time import sleep, time, localtime # for, well, timing things!

# text handling
import csv # for reading and writing the CSV stat "database"
from base64 import b64encode, b64decode # for credential encryption
import string

#HTML handling
import mechanize # to emulate a browser with JS support
import bs4 # for parsing the html

# QT
from PySide.QtCore import *
from PySide.QtGui import *

# high-level file handling
import shutil
import glob

# own stuff
from donate_test import DonateWebView, write_html
import mwo_peewee as c2p

from halloween2014 import EventQWeb

from tourney_analyzer import TourneyAnalyzer

import win32com.client
win32com.client.pythoncom.CoInitialize()

encode = b64encode # shorthands so I can use proper crypt stuff later
decode = b64decode # ditto

import ctypes
SendInput = ctypes.windll.user32.SendInput
# C struct redefinitions for DirectInput key presses
PUL = ctypes.POINTER(ctypes.c_ulong)
class KeyBdInput(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", PUL)]

class HardwareInput(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong),
                ("wParamL", ctypes.c_short),
                ("wParamH", ctypes.c_ushort)]

class MouseInput(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong),
                ("time",ctypes.c_ulong),
                ("dwExtraInfo", PUL)]

class Input_I(ctypes.Union):
    _fields_ = [("ki", KeyBdInput),
                 ("mi", MouseInput),
                 ("hi", HardwareInput)]

class Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong),
                ("ii", Input_I)]

def PressKey(hexKeyCode):
    extra = ctypes.c_ulong(0)
    ii_ = Input_I()
    ii_.ki = KeyBdInput( 0, hexKeyCode, 0x0008, 0, ctypes.pointer(extra) )
    x = Input( ctypes.c_ulong(1), ii_ )
    ctypes.windll.user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

def ReleaseKey(hexKeyCode):
    extra = ctypes.c_ulong(0)
    ii_ = Input_I()
    ii_.ki = KeyBdInput( 0, hexKeyCode, 0x0008 | 0x0002, 0, ctypes.pointer(extra) )
    x = Input( ctypes.c_ulong(1), ii_ )
    ctypes.windll.user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))


    

def mech_snapshot_filename(days_offset):
    pattern = "Mech-stats-%s.html"
    date = QDateTime.currentDateTime().addDays(days_offset)
    weekday = date.toString().split(" ")[0]
    return pattern % weekday

def check_sourceforge_version(html):
    """

    :param html: html from sourceforge page to look for a version number in
    :return: str version found
    """
    import re
    regex=re.compile("Download MWOMonitor_(.*?)\.zip", re.DOTALL | re.MULTILINE)
    try:
        match = regex.search(html)
        if len(match.groups())>0:
            return match.group(1)
    except Exception, err:
        print "Couldn't match :(", err, err.message

    return None


# noinspection PyPep8Naming,PyAttributeOutsideInit
class MechStatsPlus(c2p.MechStats):
    """
    Class to interface the singleMechStats class in here with a peewee database
    """

    def fromSingleMechStats(self, SMS):
        assert isinstance(SMS, SingleMechStats)
        self.Mech = SMS.Mech
        self.Time = SMS.Time
        self.Account = SMS.Account
        self.Matches = SMS.MatchesPlayed
        self.Wins = SMS.Wins
        self.Losses = SMS.Losses
        self.ExpTotal = SMS.XPTotal
        self.Kills = SMS.Kills
        self.Deaths = SMS.Deaths
        self.DamageDone = SMS.DamageTotal
        self.ExpPG = (0.1 + SMS.XPTotal) / (.1 + SMS.MatchesPlayed)
        #self.TimePlayed = # is this missing in the peewee model as well?
        self.WLRatio = SMS.WLRatio
        self.KDRatio = SMS.KillToDeathRatio

        self._meta.db_table = "mechstats"


class MechStatsSnapshot(QObject):
    """     Handles the scraping and storing of the Mech Stats page
    """

    def __init__(self, html=None):
        super(MechStatsSnapshot, self).__init__()
        self.html = html
        self.data = [] # field of dictionaries like the csv.DictWriter uses
        self.mechs = []

        self.parse()

    def parse(self):
        if self.html:
            self.data = self.table_dict_reader(self.html, "NOACCOUNT")
        if len(self.data):
            self._data_to_mech_stats()

    def mech_data_by_name(self, mechname):
        for m in self.mechs:
            if mechname in m.Name:
                return m
        return None

    def data_for_mech(self, mech):
        result = None
        for x in self.data:
            if mech in str(x): # MAYBE do correctly -  oh so quick and dirty ;)
                return x #
        return result

    def diff_list(self, other):
        """
        returns a list of mech diffs that changed between both
        :param other: MechStatsSnapshot
        :return: list
        """
        assert (isinstance(other, type(self)))
        result = []

        if not len(self.mechs):
            return result

        for this_mech in self.mechs:
            assert (isinstance(this_mech, SingleMechStats))
            this_name = this_mech.Name
            other_mech = other.mech_data_by_name(this_name)
            try:
                if other_mech == None:
                    print "Mech %s not found! Not played before?" % this_name
                    other_mech = SingleMechStats()
                    other_mech.zero()

                    #print "names: self, other: " , this_name, other_mech
                    #print "self"  , this_mech.data
                    #print "other", other_mech.data

                    diff = this_mech

                    #print "************ diff - ",diff
                    #print "************" , diff.data
                else:
                    diff = this_mech - other_mech
                    #if this_mech.MatchesPlayed != other_mech.MatchesPlayed:
                    #    result.append(this_mech-other_mech)
                if diff.Wins + diff.Losses > 0:
                    #print "Appending"
                    result.append(diff)
                    #print "result:", "\n".join([str(x) for x in result])
            except AttributeError:
                print "Mech not played before!"
                print "names: self, other: ", this_name, other_mech
                print "self, other: ", this_mech.data, other.data
                raise
        print "FINAL result:", "\n".join([str(x) for x in result])

        return result


    def _data_to_mech_stats(self):
        self.mechs = [SingleMechStats(l) for l in self.data]

    def csv_reader(self, csv_file):
        self.data = []
        with open(csv_file) as f:
            r = csv.DictReader(f.readlines())

        for line in r:
            r_keys = line.keys()
            r_values = line.values()
            keys = [k.translate(None, "# ") for k in r_keys]
            values = [v.translate(None, ",") for v in r_values]
            self.data.append(dict(zip(keys, values)))

        print len(self.data), " entries converted from CSV"

    def table_dict_reader(self, html, account):
        """
        :param html: str
        :param filename: str
        :param account: str
        :return: array of dict() with the data
        """
        html = self.html or html
        s = bs4.BeautifulSoup(html)
        table = s.find('table')
        rows = table.findAll('tr')
        dt = localtime()
        query_time = "%04d-%02d-%02d %02d:%02d" % (dt.tm_year, dt.tm_mon, dt.tm_mday, dt.tm_hour, dt.tm_min)

        keys = []
        lines = []
        for r in rows:
            hdrs = ["" + str(c.text).translate(None, " '") for c in r.findAll('th')]
            tds = [str(c.text).translate(None, "\n\r,") for c in r.findAll('td')]
            if len(hdrs):
                # we got headers, lets make the dict() template
                keys = hdrs
                keys.append("Time")
                keys.append("Account")
            else:
                # we got data
                if not keys:
                    raise AttributeError, "Parse mech stats: Details found, but no header :("
                    #line=dict([(k,"") for k in keys])
                tds.append(query_time)
                tds.append(account)
                line = dict(zip(keys, tds))

                #print line
                lines.append(line)

                #cells = tds
                #line["Time"] = query_time # cells.append(query_time)
                #line["Account"] = account # cells.append(account)
                #wr.writerow(cells)

        self.data = lines
        return lines

    def write_to_file(self, filename):
        if not self.html:
            print "%s has no html to write :(" % str(self)
            return False
        if os.path.exists(filename):
            os.unlink(filename)
        with open(filename, "wt") as f:
            f.write(self.html)
            print "%s data written to %s" % (str(self), filename)
        return True

    def read_from_file(self, filename):
        with open(filename, "rt") as f:
            self.html = f.read()
            self.parse()
            print "%s data loaded from %s" % (str(self), filename)
        return True

# noinspection PyPep8Naming
class SingleMechStats(QObject):
    """ Handles the storage of a single Mech's stats
    """

    def __init__(self, data_dictionary=None):
        super(SingleMechStats, self).__init__()
        if not data_dictionary:
            self.zero()
        self.data = data_dictionary

    def _init_from_data(self, dictionary=None):
        self.data = dictionary or self.data
        if not len(self.data):
            raise AttributeError, "Need data dictionary to create MechStats"
            #print "No need to parse anything! ;)"

    def zero(self):
        """returns self so you can use it as a pseudo-mech factory"""
        keys = "Mech,Account,MatchesPlayed,Kills,Deaths,Wins,Losses,TimePlayed,Time,DamageDone,XPEarned,Ratio".split(
            ",")
        values = ["0" for x in keys]
        stats = dict(zip(keys, values))
        self._init_from_data(stats)
        return self

    def __str__(self):
        params = (
            self.Name[:20], self.Wins, self.Losses, self.WLRatio, self.Kills, self.Deaths, self.KillToDeathRatio, self.DPG)
        return '%-21s: %3dW %3dL %5.1fWL%% - %3dK %3dD %5.2fK/D %3dDPG' % params

    def __gt__(self, other):
        return self.DPG > other.DPG

    def __sub__(self, other):
        result = dict()
        for key in self.data.keys():
            try:
                result[key] = float(self.data[key]) - float(other.data[key])
            except:
                result[key] = other.data[key]

        result_mech = SingleMechStats(result)
        return result_mech

    def __add__(self, other):
        result_dict = {}
        for key in "Deaths,Kills,MatchesPlayed,DamageDone,Wins,Losses,XPEarned".split(","):
            #data_type = type(self.data.get(key,0))
            #result_dict[key] = self.data.get(key,0) + data_type(other.data.get(key,0))
            s_v = self.data.get(key, 0)
            o_v = other.data.get(key, 0)
            try:
                if not ( (type(s_v) == type("")) and (type(o_v) == type("") )):
                    s_v = float(s_v)
                    o_v = float(o_v)
                else:
                    print "both strings"

                result_dict[key] = s_v + o_v
            except:
                print "Couldn't combine <", s_v, "> and <", + o_v, ">"
                print "(Types: ", type(s_v), type(o_v)
                result_dict[key] = s_v

        if self.Mech == other.Mech:
            result_dict["Mech"] == self.Mech
        else:
            result_dict["Mech"] = "Several Mechs"

        result = SingleMechStats(result_dict)
        return result

        raise NotImplementedError #NEXT - add those to give combined mech session stats !!

    @property
    def Account(self):
        return self.data["Account"]

    @property
    def Deaths(self):
        return int(self.data["Deaths"])

    @property
    def Kills(self):
        return int(self.data["Kills"])

    @property
    def Wins(self):
        return int(self.data["Wins"])

    @property
    def Losses(self):
        return int(self.data["Losses"])

    @property
    def WinPercent(self):
        if (self.Losses + self.Wins) <0.01:
            return 0
        else:
            return 100 * (0.0 + self.Wins) / (0.0 + self.Losses + self.Wins)

    @property
    def WLRatio(self):
        return self.WinPercent

    @property
    def MatchesPlayed(self):
        return int(self.data["MatchesPlayed"])

    @property
    def DamageTotal(self):
        return long(self.data["DamageDone"])

    @property
    def Damage(self):
        return self.DamageTotal

    @property
    def Mech(self):
        return self.data["Mech"]

    @property
    def Name(self):
        return self.Mech

    @property
    def TimePlayed(self):
        return self.data["TimePlayed"]

    @property
    def KillToDeathRatio(self):
        if self.Deaths < 0.01: return 99
        return float((0.0 + self.Kills) / (0.0 + self.Deaths))

    @property
    def KDR(self):
        return self.KillToDeathRatio

    @property
    def XPTotal(self):
        return long(self.data["XPEarned"])

    @property
    def DamagePerGame(self):
        if self.MatchesPlayed < 0.01: return 0
        return self.DamageTotal / (0.0 + self.MatchesPlayed)

    @property
    def DPG(self):
        return self.DamagePerGame

    @property
    def Time(self):
        return self.data["Time"]

#
# def mech_progression_report(mechs, mechname, match_diff):
#     #assert(isinstance(mechs,type([])))
#     assert (isinstance(mechs[0], SingleMechStats))
#     assert (isinstance(mechname, str))
#     assert (isinstance(match_diff, int))
#
#     result_lines = []
#     mechs = [m for m in mechs if mechname in m.Name]
#     old = mechs[0]
#     for x in mechs:
#         if x.MatchesPlayed > old.MatchesPlayed + match_diff:
#             result_lines.append(str(x - old))
#             old = x
#     return result_lines
#

class SingleMechStatsCSVReader:
    """Reads a csv file into an array of SingleMechStats"""

    def __init__(self, csvfile):
        self.mechs = self.parse_csv(csvfile)
        self.data = []

    def parse_csv(self, csvs):
        data = self.csv_to_data(csvs)
        mechs = [SingleMechStats(d) for d in data]
        return mechs

    def csv_to_data(self, csvfile):
        #m=[]
        self.data = []
        with open(csvfile) as f:
            r = csv.DictReader(f.readlines())

        for line in r:
            r_keys = line.keys()
            r_values = line.values()
            keys = [k.translate(None, "# ") for k in r_keys]
            values = [v.translate(None, ",") for v in r_values]
            self.data.append(dict(zip(keys, values)))

        return self.data

    def __getitem__(self, item):
        return self.mechs[item]


class BaseStats:
    def __init__(self, html):
        self.html = html
        self.setup()
        self.parse()

    # noinspection PyAttributeOutsideInit
    def setup(self):
        self.lines = [] #MAYBE / CHECK : has lines with indexes that correspond to weaponIDs
        self.data = dict()

    def entry_string(self):
        entries = []
        for key in self.data.keys():
            entries.append("%-30s: %12s" % (key, self.data[key]))
        result = "\n".join(entries)
        return result

    def __str__(self):
        #return str(self.data)
        win_pct = self.WinRate()
        avg_xp = float(self.data.get("Avg. XP Per Match", -1  ))
        kd_ratio = float(self.data.get("Kill / Death Ratio", -1))
        games = self.MatchesPlayed()
        return "Base Stats: %d Matches (%4.1f%% Wins), %d AvgXP, %.2f K/D" % (games, win_pct, avg_xp, kd_ratio)

        #return self.entry_string()

        #result=""
        #for idx in range(len(self.data.values()[0])):
        #    result+=self.entry_string(idx)
        #return result

    def __sub__(self, other):
        assert(issubclass(type(other),type(self)))
        diff = BaseStats("")

        for key in self.data.keys():
            val = self.data.get(key,0)
            try:
                diff.data[key] = float(val) - other.data[key]
            except:
                diff.data[key] = val

        return diff


    def CBills(self):
        #assert isinstance(self.data,type([]))
        try:
            return float(self.data.get("C-Bills", "0"))
        except Exception, e:
            print e
            return 0

    def Wins(self):
        try:
            return float(self.data.get("Wins", "0"))
            #print "Wins - ",
            #print self.data["Wins"]

        except Exception, e:
            print e
            return 0

    def Losses(self):
        try:
            return float(self.data.get("Losses", "0"))
            #print self.data["Wins"]
        except Exception, e:
            print e
            return 0

    def MatchesPlayed(self):
        return self.Wins() + self.Losses()

    def WinRate(self):
        return (100 * self.Wins() + 1) / (1 + (self.Wins() + self.Losses()))

    def Kills(self):
        try:
            return float(self.data.get("Kills", "0"))
        except Exception, e:
            print e
            return 0
            
    def Deaths(self):
        try:
            return float(self.data.get("Death", "0"))
        except Exception, e:
            print e
            return 0

    def XP(self):
        try:
            return float(self.data.get("Experience Points", "0"))
        except Exception, e:
            print e
            return 0

    def parse(self):
        self.setup()

        if not len(self.html):
            print "FATAL ERROR: no html"
            raise SystemExit

        soup = bs4.BeautifulSoup(self.html)
        table = soup.find('table')
        rows = table.findAll('tr')

        for index, row in enumerate(rows):
            headers = ["" + c.text for c in row.findAll('th')]
            tds = [c.text.replace('\n', '').replace('\r', '') for c in row.findAll('td')]

            #skip headers
            if len(headers):
                continue
            else:
                cells = tds
                label = cells[0]
                data = cells[1].replace(",", "")
                if "/" in data:
                    label, label1 = label.split("/")
                    data, data1 = data.split("/")
                    self.data[label1.strip()] = data1.strip()
                self.data[label.strip()] = data.strip()
                self.lines.append(" / ".join([str(cell) for cell in cells]))
                #self.data["Line"].append(index)

    def __eq__(self, other):
        #s1 = str(self)
        #s2 = str(other)
        #result = (s1 == s2)

        #print "comparing \n'%s' and \n'%s' , \nresult: %s " % (s1,s2,result)
        #print "CB1 %d CB2 %d" % (self.CBills(),other.CBills())
        return self.CBills() == other.CBills()

    def diff_str(self, other):
        assert isinstance(other, type(self))
        c_bills = self.CBills() - other.CBills()
        wins = self.Wins() - other.Wins() - self.Losses() + other.Losses()
        kills = self.Kills() - other.Kills()
        experience = self.XP() - other.XP()
        deaths = self.Deaths() - other.Deaths()
        #result = "BaseStats diff_str error :("
        if wins > 0:
            result = "WIN with %d Kills, %d XP and %d CB gained" % ( kills, experience, c_bills )
            if (deaths >= 1):  
              result = result + " with a Death"
            else:
              result = result + " with no Death"
            
            #Update win counter file
            f = open('wins.txt', 'r+')
            winCount = int(f.read())
            winCount += 1
            print "New win count: " + str(winCount)
            f.seek(0)
            f.write(str(winCount))
            f.truncate()
            f.close()
            
            snd = QSound("win.wav") # TODO move to at least DiffChecker
            snd.play()
            
            #Take screenshot
            sleep(14)
            snapsnd = QSound("snap.wav")
            snapsnd.play()
            PressKey(0x58)
        else:
            if wins < 0:
                result = "LOSS with %d Kills, %d XP and %d CB gained" % ( kills, experience, c_bills )
                if (deaths >= 1):
                  result = result + " with a Death"
                else:
                  result = result + " with no Death"
                
                f = open('losses.txt', 'r+')
                lossCount = int(f.read())
                lossCount += 1
                print "New loss count: " + str(lossCount)
                f.seek(0)
                f.write(str(lossCount))
                f.truncate()
                f.close()

                snd = QSound("loss.wav") # TODO move to at least DiffChecker
                snd.play()
                
                #Take screenshot
                sleep(14)
                snapsnd = QSound("snap.wav")
                snapsnd.play()
                PressKey(0x58)                  
            else:
                result = "C-Bills change: " + str(c_bills)
        return result

    def detailed_diff_str(self, other):
        assert isinstance(other, type(self))
        c_bills = self.CBills() - other.CBills()
        wins = self.Wins() - other.Wins()
        losses = + self.Losses() - other.Losses()
        experience = self.XP() - other.XP()
        kills = self.Kills() - other.Kills() # CHECKME is this not in base results?! :(
        deaths = self.Deaths() - other.Deaths()
        result = "%d games (%dW/%dL) with %d XP, %d CBills, %d kills, and %d deaths" % \
            ( wins + losses, wins, losses, experience, c_bills, kills, deaths )    
        return result


class WeaponStats:
    def __init__(self, html):
        self.html = html
        self.setup()
        self.parse()

    # noinspection PyAttributeOutsideInit
    def setup(self):
        self.weaponIDs = dict() # CHECKME - needed? - line # that weapon of index is on
        self.weapons = [] # list of weapons, index = line in source table
        self.headers = [] # CHECKME: fill
        self.lines = [] # has lines with indexes that correspond to weaponIDs
        self.data = dict() # entry["Name"]=value, e.g. "C-Bills": 19999

    def __str__(self):
        #return str(self.data)
        result = ""
        if len(self.data) == 0:
            return result
        for idx in range(len(self.data.values()[0])):
            result += self.entry_string(idx)
        return result

    def entry_string(self, idx):
        wpn = self.data['Weapon'][idx]
        fired = str(self.data['Fired'][idx]).replace(",", "")
        hit = str(self.data['Hit'][idx]).replace(",", "")
        dmg = str(self.data['Damage'][idx]).replace(",", "")
        result = '%20s: %8d Fired, %8s Hits, %8.0f Damage' % (wpn, int(fired), int(hit), float(dmg))

        return result

    def parse(self):
        self.setup()

        if not len(self.html):
            print "FATAL ERROR: no html"
            raise SystemExit

        soup = bs4.BeautifulSoup(self.html)
        table = soup.find('table')
        rows = table.findAll('tr')

        for index, row in enumerate(rows):
            headers = ["" + c.text for c in row.findAll('th')]
            tds = [c.text.replace('\n', '').replace('\r', '') for c in row.findAll('td')]
            if len(headers):
                self.headers = [hdr for hdr in headers]
                self.data = dict([(hdr, []) for hdr in self.headers])
                self.data["Line"] = []
            else:
                cells = tds
                weapon = str(cells[0])
                self.weapons.append(weapon)
                self.weaponIDs[weapon] = index
                self.lines.append(" / ".join([str(cell) for cell in cells]))
                for cell_index, cell in enumerate(cells):
                    field_name = self.headers[cell_index]
                    self.data[field_name].append(str(cell))
                self.data["Line"].append(index)

    def stats_by_weapon(self, weapon_name):
        weapon_id = self.get_weapon_id(weapon_name)
        result = self.entry_string(weapon_id)
        return result

    def weapon_dict(self, weapon_name):
        weapon_id = self.get_weapon_id(weapon_name)
        result = {}
        for key, value in self.data.items():
            result[key] = value[weapon_id]
        return result

    def details_by_weapon(self, weapon):
        #result = ""
        weapon_id = self.get_weapon_id(weapon)
        try:
            result = "WEAPON %-20s - IDX %3d : %s" % (weapon, weapon_id, self.lines[weapon_id])
        except IndexError:
            print("WEAPON ID %d NOT FOUND for weapon %s" % (weapon_id, weapon))

            print "\nWEAPONS"
            print self.weapons
            print "\nWEAPON IDs"
            print self.weaponIDs

            raise IndexError

        return result


    def get_weapon_id(self, weapon):
        weapons = self.data["Weapon"]
        try:
            wpn_id = weapons.index(weapon)
        except ValueError:
            wpn_id = -1
        return wpn_id
        #return self.weaponIDs.get(weapon, -1)


    def same_data(self, other):
        assert (isinstance(other, type(self)))
        return str(self) == str(other)


    def stat_differences(self, other):
        assert (isinstance(other, type(self)))
        diffs = ["DIFFERENCES FOUND:"]

        if self.same_data(other):
            return "NO DIFFS!"

        for this_weapon in self.weapons:
            #print this_weapon,
            own_str = self.stats_by_weapon(this_weapon)
            try:
                other_str = other.stats_by_weapon(this_weapon)
            except IndexError:
                other_str = "*** NEW WEAPON ***"

            if own_str != other_str:
                diffs.append("NEW: " + other_str)
                diffs.append("OLD: " + own_str)

        return "\n".join(diffs)

    def weapon_diff_str(self, other, weapon):
        assert (isinstance(other, type(self)))
        fields = ["Fired", "Hit", "Damage"]
        own_id = self.get_weapon_id(weapon)
        #other_id = other.get_weapon_id(weapon)
        diffs = ["%-20s " % weapon + " : "]
        self.results = {}
        for field in fields:
            mine = str(self.data[field][own_id]).replace(",", "")
            theirs = str(other.data[field][own_id]).replace(",", "")
            diff = float(mine) - float(theirs)
            self.results[field] = diff
            diffs.append("%s: %4.0f " % (field, diff))

        #diffs.append("Hit%%: %3f" % (1+float(self.results["Hit"]))/(1+float(self.results["Fired"])))
        return "\t".join(diffs)

    def weapon_stat_differences(self, other):
        assert (isinstance(other, type(self)))
        diffs = [""]

        if self.same_data(other):
            return "NO DIFFS!"

        total_damage = 0.0
        for this_weapon in self.weapons:
            #print this_weapon,
            own_str = self.stats_by_weapon(this_weapon)
            try:
                other_str = other.stats_by_weapon(this_weapon)
            except IndexError:
                other_str = "*** NEW WEAPON ***"

            if own_str != other_str:
                diffs.append(self.weapon_diff_str(other, this_weapon))
                total_damage += self.results["Damage"]

        diffs.sort()
        diffs.append("%s: %4.0f \n" % ("TOTAL DAMAGE", total_damage))

        return diffs


class HtmlOpenThread(QRunnable):
    browserSemaphore = QSemaphore(1)

    def __init__(self, browser, page=None, cb=None, timeout=3, url=None):
        """
        :param browser:
        :param page:
        :param cb: callback function that will be called with the html
        :param timeout:
        :param url: Provide this if you DON'T want the URL of a profile page constructed but have a fixed URL
        :return: will return the html via callback as a parameter
        """
        super(HtmlOpenThread, self).__init__()
        self.page = page or ""
        self.url = url or r""
        self.browser = browser
        #self.is_done = True
        self.callback = cb
        self.timeout = timeout

    def run(self, page=None, cb=None):
        if not self.browserSemaphore.tryAcquire(1, self.timeout * 1000):# try to get a browser lock for 2 seconds
            print "HTMLOpenThread.run Couldn't get a browser lock for %s seconds" % self.timeout
            #if not self.is_done:
        #    print "Not done with previous html request, trying again in a second"
        #    QTimer().singleShot(1000,lambda : self.run(page,cb))

        #self.is_done = False
        self.url = self.url or r"https://mwomercs.com/profile/stats?type=" + self.page

        print "HTMLOpenThread -> " + self.url,
        #print "HTMLOpen requesting page %s" % self.url
        #print "Callback going to %s" % str(self.callback)
        #print "Threaded page scraping %s" % self.url

        try:
            self.response = self.browser.open(self.url)
            self.html = self.response.read()
            print "OK!"
            if self.callback:
                self.callback(self.html)
        except AttributeError, err:
            print "Couldn't read html from ", self.url, " :'(. Maybe thread deleted before response? oO"
            print err, err.message
        self.browserSemaphore.release(1)
        #self.emitter.emit(SIGNAL('update(str)'), self.html)
        # CHECKME :  not in QRunnable :( - check if self.emitter.emit() works

        #self.is_done = True
        return


class MWOLoginThread(QRunnable):
    sig_done = Signal(int)
    sig_captcha = Signal(int)
    sig_status = Signal(str)
    browserSemaphore = QSemaphore(1)

    def __init__(self, browser, email, password, callback=None):
        super(MWOLoginThread, self).__init__()
        self.email = email
        self.password = password
        self.browser = browser
        self.logged_in = False
        self.callback = callback
        self.is_captchad = False

        self.status_callback = None
        #self.is_done = True

        #if not self.is_done:
        #    print "Not done with previous login, trying again in a second"
        #    QTimer().singleShot(1000,lambda : self.run())
        #

        #self.is_done = False
        #print "Login thread running"
        #self.response = self._login()
        #print "Threaded login complete"
        #self.is_done = True

    def set_status_callback(self, func):
        self.status_callback = func

    def status(self, txt):
        if self.status_callback:
            self.status_callback(txt)

    def run(self):
        email = self.email
        password = self.password
        if self.browserSemaphore.tryAcquire(1, 5000):# try to get a browser lock for 2 seconds
            print "Browser lock acquired!"
        else:
            print "MWOLoginThread.run Couldn't get a browser lock for 5 seconds"
            return

        browser = self.browser
        browser.open("https://mwomercs.com/login") #?return=/profile/stats/?type=mech
        try:
            browser.select_form(nr=0)
            browser['email'] = email
            browser['password'] = password
            response = browser.submit()
            self.html = response.read()
        except:
            self.logged_in = 0

        self.browserSemaphore.release(1)

        if "LOGOUT" in self.html:
            self.logged_in = True
        else:
            print "LOGIN FAILED. Are your credentials correct?"
            print "Credentials used: %s - %s..%s" % (email, password[:3], password[-3:])
            self.logged_in = False
            #self.sig_status.emit("Login failed, wrong credentials?")

            self.status("Login failed, wrong credentials?")

            with open("login-fail.html", "wt") as f:
                f.write(self.html)

        if "Please enter the captcha" in self.html:
            self.is_captchad = True
            #self.sig_status.emit("It appears you are under captcha restriction. :'(. Please check the FAQ.")
            #self.sig_captcha.emit(self.is_captchad)
            self.status("It appears you are under captcha restriction. :'(. Please check the FAQ.")


        #print("Emitting %d" % self.logged_in)
        # NOT WORKING :( #self.emitter.emit(SIGNAL('login(int)'), self.logged_in)
        #self.emitter .. .sig_done.emit(self.logged_in)
        #self.is_done=True

        if self.callback:
            print"callback delivering -> " + str(self.logged_in)
            self.callback(self.logged_in)

            #return response


class MWODiffChecker(QObject):
    sigStatus = Signal(str)
    sigMessage = Signal(str)
    sigLoginFail = Signal()
    sigLoginOK = Signal()
    sigMaintenanceOver = Signal()

    def __init__(self, email, password):
        super(MWODiffChecker, self).__init__()
        self.email = email
        self.password = password
        self.old_stats = None
        self.new_stats = None
        self.logged_in = False
        self.is_changed = False
        self.browser = mechanize.Browser()
        self.is_changed = False
        self.new_weapon_results = None
        self.base_result_str = ""
        self.server_maintenance = False

        self.base_stats_old = None
        self.base_stats_new = None
        self.base_stats_session_start = None

        self.mech_stats_session_start = None
        self.mech_stats = None

        #self.html_thread=HtmlOpenThread(self.browser,"",None)
        #self.html_thread=None
        #self.login_thread=None
        self.last_login_attempt_time = time() - (LOGIN_THROTTLE - 1) # may log in in 1 second
        self.may_login = True

        self.auto_show_mech_report = False
        self.check_challenge = False
        self.challenge_status = ""

        self.session_XP = 0
        self.session_CBills = 0
        self.session_kills = 0
        self.session_wins = 0
        self.session_losses = 0

        #weapon_stats *sometimes* reports not logged in?! Trying to deal with that
        self._weapon_stats_error_count = 0

        # noinspection PyTypeChecker
        QTimer().singleShot(1500, lambda: self.threaded_login())
        print "MWODiffC logging in ifrom init() in 1 second"

        QTimer().singleShot(12000, lambda: self.check_for_sourceforge_update())

        QTimer().singleShot(15000, lambda: self.check_maintenance())
        #self.threaded_login()



    def allow_login(self, true_or_false):
        print self, "allow_login() received", true_or_false
        self.may_login = False
        if true_or_false:
            self.may_login = True

    def check_maintenance(self):
        """
        will check if the server is in maintenance, hand over to receive_.. function to send a signal
        :return: None
        """
        print "Checking for maintenance.."
        if not self.server_maintenance:
                QTimer().singleShot(120000,lambda: self.check_maintenance()) # 2 minutes
        status_url = "http://mwomercs.com/status"
        getter = HtmlOpenThread(self.browser,None,self.receive_maintenance_status,10,status_url)
        getter.autoDelete()
        getter.setAutoDelete(True)
        QThreadPool.globalInstance().start(getter)


    def receive_maintenance_status(self,html):
        """
        callback function, Will analyze the status html, will manage self.server_maintenance
        and emit sound/signal if over. Will re-schedule check_maintenance during maintenances
        :param html: the status page html
        :return: None
        """
        offline_text = 'Game Servers: Offline'
        print "Was in maintenance :", self.server_maintenance
        if self.server_maintenance:
            if offline_text in html:
                self.server_maintenance = True
                self.sigStatus.emit("Still in maintenance")
            else:
                self.server_maintenance = False
                self.sigStatus.emit("Maintenance over!")
                self.sigMaintenanceOver.emit()
                self.sound_maintenance_over()
        else: # previously no maintenance
            if offline_text in html:
                self.server_maintenance = True
                self.sigStatus.emit("!!! SERVER IN MAINTENANCE !!!")
                self.sigMessage.emit("\n\n!!! SERVER IN MAINTENANCE !!!\n\n")
                self.sigMessage.emit("Suspending login attempts. I'll alert you with a sound when it comes back up!")
        
        print "New maintenance status :", self.server_maintenance

        if self.server_maintenance:
            QTimer().singleShot(10000,lambda: self.check_maintenance())
            print "Setting timer to check for maintenance again in 10 seconds"


    def sound_maintenance_over(self):
        QSound("maintenance_over.wav").play()

    def get_new_weapon_results(self):
        if self.is_changed:
            self.is_changed = False
            results = self.new_weapon_results[:]
            self.new_weapon_results = []
            return results
        else:
            return []

    def threaded_get_page(self, page, callback):
        #url = r"https://mwomercs.com/profile/stats?type=" + page
        #print "Threaded Getting page: ", page
        opener = HtmlOpenThread(self.browser, page, callback)
        opener.autoDelete()
        opener.setAutoDelete(True)

        # noinspection PyArgumentList
        QThreadPool.globalInstance().start(opener)


    def get_page(self, page): # MAYBE - used by CSV() - replace with threaded version for no GUI freeze
        url = r"https://mwomercs.com/profile/stats?type=" + page
        response = self.browser.open(url)
        content = response.read()
        assert isinstance(content, str)
        return content

    def onLoginReceived(self, logged_in):
        print "received login:", logged_in
        self.logged_in = logged_in
        if not logged_in:
            print"Login failed, current credentials:"
            print "<<%s>> , <<%s>>" % (self.email, self.password)
            self.sigLoginFail.emit()
        else:
            self.sigLoginOK.emit()

    def threaded_login(self):
        print "threaded login!"
        if self.server_maintenance:
            print "..aborted, because server is in maintenance!"
            self.check_maintenance()
            return

        if not self.may_login:
            msg = "Login not allowed (checkbox unchecked)"
            self.sigStatus.emit(msg)
            print msg
            return 0

        login_diff = time() - self.last_login_attempt_time
        if login_diff < LOGIN_THROTTLE:
            msg = "Last login attempt was %d seconds ago. Waiting a bit" % login_diff
            self.sigStatus.emit(msg)
            print msg
            return 0

        if self.password == DEFAULT_PASSWORD:
            self.sigMessage.emit("Password seems to not be set yet. Not logging in for now.")
            return

        print "All good, trying to login."
        self.sigMessage.emit("Logging in")
        self.last_login_attempt_time = time()

        login_thread = MWOLoginThread(self.browser, self.email, self.password, self.onLoginReceived)
        login_thread.autoDelete()
        login_thread.setAutoDelete(True)
        login_thread.set_status_callback(self.onLoginStatus)

        # errmahgerd, new style QT signals are a mess in PySide?!

        #login_thread.sig_status[str].connect(self.onLoginStatus)
        # NO :( self.connect(login_thread, SIGNAL("sig_status()"), self.onLoginStatus)
        # NEITHER :( ?? MAYBE self.connect(login_thread, SIGNAL("sig_status(str)"), self.onLoginStatus)

        # noinspection PyArgumentList
        QThreadPool.globalInstance().start(login_thread)

        #login_thread.deleteLater()
        #t.wait()
        #t.deleteLater()

    def onLoginStatus(self, txt):
        self.sigStatus.emit("Login issue: " + txt)
        self.sigMessage.emit("Login issue: " + txt)

    def _weapon_stat_receiver(self, html):
        if not self.new_stats:
            self.old_stats = WeaponStats(html)
            self.new_stats = WeaponStats(html)
            self.is_changed = False
        else:
            self.old_stats = WeaponStats(self.new_stats.html)
            self.new_stats = WeaponStats(html)
            self.is_changed = not self.new_stats.same_data(self.old_stats)

        self.html_thread.deleteLater()

        return self.is_changed

    def check(self):
        """gets the weapon stats via thread which is then processed by process_weapon_stats"""
        if not self.logged_in:
            self.threaded_login()
            #QTimer().singleShot(2000,lambda: self.check())
            #return
        #print "Getting weapon page"
        self.threaded_get_page("weapon", self.process_weapon_stats)
        if self.check_challenge:
            self.threaded_get_page("challenges", self.process_challenge)

    def process_challenge(self, html):
        import re
        if not self.check_challenge:
            return

        time_left = re.compile("(\d+:\d+:\d+)</span>")
        done = re.compile("(\d{1,3} out of \d{1,3})")
        done_msg = "Challenge status unknown. No challenge active?"
        try:
            done_results = done.findall(html)
            if len(done_results):
                done_msg = done_results[0]
            else:
                if "CHALLENGE COMPLETE" in html:
                    done_msg = "Challenge complete. Well done!"
        except:
            done_msg = "Couldn't get challenge results"

        if done_msg != self.challenge_status:
            self.sigMessage.emit("Challenge status: %s \n" % done_msg)
            self.challenge_status = done_msg
            if "done!" in done_msg:
                try:
                    snd = QSound("cheer.wav")
                    snd.play()
                except:
                    print "Couldn't play cheer sound"



    def process_weapon_stats(self, weapon_html):
        #print "Weapon stats recieved!"
        new_html = weapon_html

        if not new_html:
            print "## ERROR: process_weapon_stats received empty html"
            return

        # check if stats have never been stored (=1st run)
        if not self.new_stats:
            print "new stats: len  ", len(new_html)
            self.old_stats = WeaponStats(new_html)
            self.new_stats = WeaponStats(new_html)
            self.is_changed = False
        else:
            self.old_stats = WeaponStats(self.new_stats.html)
            try:
                self.new_stats = WeaponStats(new_html)
                self._weapon_stats_error_count = 0
            except Exception, err:
                self._weapon_stats_error_count += 1
                if self._weapon_stats_error_count > 2:
                    self.logged_in = False
                    #self.status("Weapon stats fail, login expired?")
                    self.sigStatus.emit("Weapon stats failed, did you log in on the website?") #MAYBE
                    self.sigMessage.emit("Mwomercs claims you're logged in elsewhere?")
                    self.sigMessage.emit("Did you log in on the website? Are you running another instance of this app?")
                    self.sigMessage.emit("Resetting and logging in again.")
                    print "### process_weapon_stats ERROR:", err
                    with open("weapon_err.html","wt") as f:
                        f.write(new_html)
                    self._weapon_stats_error_count = 0

                else:
                    fail = self._weapon_stats_error_count
                    print "## WARNING: Weapon stats failed %d times, waiting for more to re-login" % fail
                    return False

            # reading stats worked, so resettuing error counter

            #print "new html len:" , len(new_html)
            try:
                self.is_changed = not self.new_stats.same_data(self.old_stats)
            except KeyError:
                with open("noWeaponKey.html", "wt") as f:
                    f.write(new_html)
                raise

        if self.is_changed:
            self.new_weapon_results = self.new_stats.weapon_stat_differences(self.old_stats)
        else:
            self.new_weapon_results = None

        return self.is_changed

    def __stat_diffs(self):
        # TODO deal with self.check being asynchronous now!!
        self.check()
        assert isinstance(self.new_stats, WeaponStats)
        assert isinstance(self.old_stats, WeaponStats)

        if not self.new_stats.same_data(self.old_stats):
            return self.new_stats.weapon_stat_differences(self.old_stats)

        return []

    def session_base_diff_str(self):
        assert isinstance(self.base_stats_new, BaseStats)
        assert isinstance(self.base_stats_session_start, BaseStats)
        res = self.base_stats_new.detailed_diff_str(self.base_stats_session_start)
        #res += " and %d CBills" % self.session_CBills
        return res


    def __print_session_base_diff(self):
        print self.session_base_diff_str()

    def base_check(self):
        if self.server_maintenance:
            print "Server in maintenance, not checking!"
            return
            
        if not self.logged_in:
            self.threaded_login()
            # noinspection PyTypeChecker
            QTimer().singleShot(LOGIN_THROTTLE * 1000, lambda: self.base_check())
            print "Not logged in, trying again in %d seconds" % LOGIN_THROTTLE
            self.sigStatus.emit("Not logged in, trying again in %d seconds" % LOGIN_THROTTLE)
            return
            #print "Getting base html (threaded)"

        self.sigStatus.emit("Getting base stats")

        self.threaded_get_page("base", self.process_base_html)

    def process_base_html(self, new_html):
        #print "proc_base_html parsing base html"
        try:
            base = self.base_stats_new = BaseStats(new_html)
        except AttributeError:
            self.sigStatus.emit("Error parsing base stats!")
            return

        if not self.base_stats_session_start:
            self.base_stats_session_start = BaseStats(new_html)

        if not self.base_stats_old:
            self.base_stats_old = BaseStats(new_html)
            print "Base stats initialized:"
            print self.base_stats_old
            self.sigStatus.emit(str(self.base_stats_old))
            return

        if not base == self.base_stats_old:

            print "\o/ found new base result"
            self.base_result_str = self.base_game_result()
            self.base_stats_old = BaseStats(new_html)

            # TODO: make this a menu item
            self.__print_session_base_diff()
        else:
            self.base_result_str = ""

        return self.base_result_str

    def get_base_stats_session_start(self):
        return self.base_stats_session_start

    def get_new_base_results(self): # CHECKME is this really asynchronous? I think no
        """return results if there are any, reset them"""
        #print "get_new_base_results Checking base results"
        result = self.base_result_str
        self.base_result_str = None
        return result

    def base_game_result(self):
        assert(isinstance(self.base_stats_new,BaseStats))
        if not (self.base_stats_new and self.base_stats_old):
            return "Base stats not initialized yet."
            #  result_str = self.base_result_str = "%s with %.0f CB and %.0f XP gained." % (win_str, c_bills, experience)
        result_str = self.base_result_str = self.base_stats_new.diff_str(self.base_stats_old)

        #diff_base = self.base_stats_new - self.base_stats_old
        #self.session_CBills += diff_base.CBills
        #self.session_XP += diff_base.XP

        return result_str

    def mech_stats_load_or_query(self, filename=None, reset_session=False, show_report=False):
        self.sigStatus.emit("Reading mech stats from %s" % (filename or "mwomercs.com"))

        self.auto_show_mech_report = show_report

        if not self.logged_in and not filename:
            # noinspection PyTypeChecker
            QTimer().singleShot(5000, lambda: self.mech_stats_load_or_query())
            self.sigMessage.emit("Not logged in for mech stats, retrying in 5")
            return

        if reset_session:
            print "resetting Mech session"
            self.reset_mech_session()
            print "self.mech_stats_session_start:", self.mech_stats_session_start

        if filename:
            # html=open(filename).read()
            # if reset_session:
            #     self.reset_mech_session()
            # self.process_mech_stats(html, False)
            print "Loading mech stats from ", filename
            self.mech_stats = MechStatsSnapshot()
            self.mech_stats.read_from_file(filename)
            if not self.mech_stats_session_start: # this should be None if reset_session==True
                self.sigMessage.emit("Using mech data from '%s' as session base" % filename)
                self.mech_stats_session_start = self.mech_stats
            elif show_report:
                self.mech_session_report_terse()
            return
        else:
            print "filename:", filename
            self.threaded_get_page("mech", self.process_mech_html)
            print "Getting mech stats from html!"

    def process_mech_html(self, html, show_report=False): # called from load_or_query_mech_stats callback
        print "Processing mech stats from %d long html" % len(html)
        self.sigStatus.emit("Acquired Mech stats")
        self.mech_stats = mechstats = MechStatsSnapshot(html)
        #self.sigMessage.emit("Processed %d mech" % (len(mechstats.mechs)))
        if not self.mech_stats_session_start:
            self.mech_stats_session_start = mechstats
            self.message("Using current mech data from '%s' as session base" % "MwoMercs.com")
        elif show_report or self.auto_show_mech_report:
            #self.mech_session_report_terse()
            self.mech_session_report()
        print "self.mech_stats_session_start:", self.mech_stats_session_start


    def reset_mech_session(self, stats_to_use=None):
        self.mech_stats_session_start = stats_to_use
        self.sigStatus.emit("Mech session reset.")

    def mech_session_report_terse(self):
        if not self.mech_stats:
            self.sigMessage.emit("No mech stats report without mech stats!")
            return

        result = self.mech_stats.diff_list(self.mech_stats_session_start)
        if len(result):
            sum_stats = result[0]
            if len(result) > 1:
                for x in result[1:]:
                    sum_stats = sum_stats + x
            text = "\nSession summary:\n" + str(sum_stats) + "\n"
        else:
            text = "No game/mech results yet.\n"

        self.sigMessage.emit(text)
        print text

    def mech_session_report(self):
        if (not self.mech_stats):
            print("No mech stats report without mech stats!")
            self.sigMessage.emit("No mech stats report without mech stats!")
            return

        if (not self.mech_stats_session_start):
            print("No mech stats report without session baseline!")
            self.sigMessage.emit("No mech stats report without session baseline!")
            return

        result = self.mech_stats.diff_list(self.mech_stats_session_start)
        if len(result):
            self.sigMessage.emit("Mech stats this session:\n")
            text = "\n".join([str(x) for x in result])
            text += "\n" + "-" * 40
            #sum_stats = sum(result)
            # fails with "TypeError: unsupported operand type(s) for +: 'int' and 'SingleMechStats'"

            sum_stats = result[0]
            if len(result) > 1:
                for x in result[1:]:
                    sum_stats = sum_stats + x

            text += "\n" + str(sum_stats)
        else:
            text = "Didn't find mech stats - no recorded matches or stats not refreshed yet."

        self.sigMessage.emit(text + "\n")
        print text

    def check_for_sourceforge_update(self):
        status_url = "http://sourceforge.net/projects/mwomonitor/files/"
        getter = HtmlOpenThread(self.browser,None,self.receive_sourceforge_html,10,status_url)
        getter.autoDelete()
        getter.setAutoDelete(True)
        QThreadPool.globalInstance().start(getter)

    def receive_sourceforge_html(self,html):
        sf_version = check_sourceforge_version(html)
        print "Sourceforge version found: %s" % sf_version
        if sf_version > APP_VERSION:
            self.sigMessage.emit("\nUpdate available! Your version: %s, current: %s "%(APP_VERSION,sf_version))
            self.sigMessage.emit("Use the File -> Check for Update menu item to go to the download page.\n")

class MainWidget(QWidget):
    sigShowTournament = Signal()
    screenshotLocation = SCRNSHOTLOCATION
    screenshotDestination = SCRNSHOTDESTINATION

    def __init__(self, parent=None):
        super(MainWidget, self).__init__(parent)

        self.editor = self._setup_editor()
        self.label = QLabel("..")

        self.csv_btn = QPushButton("Save Stats as .CSV", self)
        self.csv_btn.clicked.connect(self.run_stat_update)

        vlayout = QHBoxLayout()

        em = self.email_field = QLineEdit("EMAIL@SOMEWHERE.COM")
        #self.email_field.setReadOnly(True)
        em.textEdited[str].connect(self.onNewEmail)
        em.editingFinished.connect(self.new_credentials)

        pw = self.password_field = QLineEdit("PASSWORD")
        pw.setEchoMode(QLineEdit.Password)
        pw.textEdited[str].connect(self.onNewPwd)
        pw.editingFinished.connect(self.new_credentials)
        #self.password_field.setReadOnly(True)

        em_lbl = QLabel("E-mail :")
        pw_lbl = QLabel("Password :")

        self.login_checkbox = QCheckBox("Log in?", self)
        self.login_checkbox.stateChanged.connect(self.onLoginCheckbox)

        empwd_layout = QHBoxLayout()
        empwd_layout.addWidget(em_lbl)
        empwd_layout.addWidget(self.email_field)
        empwd_layout.addWidget(pw_lbl)
        empwd_layout.addWidget(self.password_field)
        empwd_layout.addWidget(self.login_checkbox)
        
        self.screenshotLocation_button = QPushButton("Browse...")
        self.screenshotLocation_field = QLineEdit("")
        self.screenshotLocation_button.clicked.connect(self.browse_screenshot_location)
        self.screenshotLocation_field.editingFinished.connect(self.setScreenshotLocation)
        
        screenshotLocation_layout = QHBoxLayout()
        screenshotLocation_layout.addWidget(self.screenshotLocation_field)
        screenshotLocation_layout.addWidget(self.screenshotLocation_button)
        
        self.screenshotDestination_button = QPushButton("Browse...")
        self.screenshotDestination_field = QLineEdit("")
        self.screenshotDestination_button.clicked.connect(self.browse_screenshot_destination)
        self.screenshotDestination_field.editingFinished.connect(self.setScreenshotDestination)
        
        screenshotDestination_layout = QHBoxLayout()
        screenshotDestination_layout.addWidget(self.screenshotDestination_field)
        screenshotDestination_layout.addWidget(self.screenshotDestination_button)    
        
        screenshotLocation_lbl = QLabel("MWO Screenshot Folder :")
        screenshotDestination_lbl = QLabel("Destination Screenshot Folder :")
        
        screenshot_layout = QFormLayout()
        screenshot_layout.addRow(screenshotLocation_lbl, screenshotLocation_layout)
        screenshot_layout.addRow(screenshotDestination_lbl, screenshotDestination_layout)

        layout = QVBoxLayout()
        layout.addWidget(self.editor)
        vlayout.addWidget(self.label)
        vlayout.addWidget(self.csv_btn)

        #wbtn=self._setup_update_button(vlayout)

        layout.addLayout(vlayout)
        layout.addLayout(empwd_layout)
        layout.addLayout(screenshot_layout)
        # Set dialog layout
        self.setLayout(layout)

        self.updates = 0
        self.games = 0
        self.poll_start = time()
        self.new_credentials_set = False
        self.base_stats_posted = False
        self.dc = None

        self.tourney_html = None

        #self.show()

        self.statusBar = None
        #self.initialize()

    # noinspection PyAttributeOutsideInit
    def initialize(self):
        self.status("Reading %s.ini" % APPNAME)
        self.settings = QSettings('%s.ini' % APPNAME, QSettings.IniFormat)
        self.parent().resize(self.settings.value('size', QSize(600, 250)))

        email_temp = self.settings.value('email', encode('email@default.com'))
        try:
            self.email = decode(email_temp)
        except:
            self.message("Unencrypted credentials found in config file.")
            self.message("(from old version?) Will store encrypted on closing the app.")
            self.email = email_temp

        pw_temp = self.settings.value('password', encode(DEFAULT_PASSWORD))
        try:
            self.password = decode(pw_temp)
        except:
            self.password = pw_temp

        last_version = self.settings.value('lastversion','')
        if APP_VERSION > last_version:
            self.show_new_since_dialog(last_version)

        # don't auto-login with the default password
        if self.password == DEFAULT_PASSWORD:
            self.login_checkbox.setChecked(Qt.Unchecked)
        else:
            self.login_checkbox.setChecked(Qt.Checked)


        #print "loaded email and pw: %s %s" % (self.email,self.password)
        self.POLL_INTERVAL = self.settings.value('POLL_INTERVAL', POLL_INTERVAL)
        self.RESULT_POST_INTERVAL = self.settings.value('RESULT_POST_INTERVAL', RESULT_POST_INTERVAL)

        self.csv_write_interval = int(self.settings.value("CSV_INTERVAL", CSV_INTERVAL))

        self.password_field.setText(self.password)
        self.email_field.setText(self.email)
        self.password_is_set = True

        if self.password == DEFAULT_PASSWORD:
            self.editor.setHtml("<h3>\nNO CREDENTIALS SET. PLEASE ENTER THEM BELOW.</h3>")
            self.password_is_set = False
        else:
            # noinspection PyArgumentList
            time_string = QDateTime.currentDateTime().toString()
            self.message("\n%s (version %s) started at %s\n" % (APPNAME, APP_VERSION, time_string))

        self.screenshotLocation_field.setText(self.settings.value('screenshotLocation', SCRNSHOTLOCATION))
        self.screenshotLocation = self.settings.value('screenshotLocation', SCRNSHOTLOCATION)
        self.screenshotDestination_field.setText(self.settings.value('screenshotDestination', SCRNSHOTDESTINATION))
        self.screenshotDestination = self.settings.value('screenshotDestination', SCRNSHOTDESTINATION)
            
        self.dc = None
        self._setup_dc()
        self._setup_timer()

        self.pilot_name = ""
        self.sigShowTournament.connect(self.show_tournament_view)

    def browse_screenshot_location(self):
      self.screenshotLocation = QFileDialog.getExistingDirectory(self, "Select MWO Screenshot Directory", '/home', QFileDialog.ShowDirsOnly or QFileDialog.DontResolveSymlinks)
      self.screenshotLocation_field.setText(self.screenshotLocation)
      
    def setScreenshotLocation(self):
      self.screenshotLocation = self.screenshotLocation_field.text()
      
    def browse_screenshot_destination(self):
      self.screenshotDestination = QFileDialog.getExistingDirectory(self, "Select Screenshot Destination Directory", '/home', QFileDialog.ShowDirsOnly or QFileDialog.DontResolveSymlinks)
      self.screenshotDestination_field.setText(self.screenshotDestination)
      
    def setScreenshotDestination(self):
      self.screenshotDestination = self.screenshotDestination_field.text()
        
    def show_new_since_dialog(self,last_version):
        message = ""
        if last_version < "07f":
            message += "## New in Version 07f:\n"
            message += "Long-term stats are saved to a persistent database in the current\n"
            message += "directory to a file called 'mechs.sqlite'. This will speed up\n"
            message += "the display of long-term stats significantly\n"
            message += "However, when you request a long-term stats report for \n"
            message += "the first time might take 1-2 minutes to set it up.\n"
            message += "\n"

        if message:
            msgBox = QMessageBox()
            msgBox.setText(message)
            msgBox.exec_()
        pass

    def _setup_donate_button(self, layout):
        b = self.web_btn = QPushButton("Donate")
        b.clicked.connect(self.open_donate_window)
        layout.addWidget(b)
        return b

    def onLoginCheckbox(self, state):
        print "onLoginCheckbox received", state
        if self.dc:
            self.dc.allow_login(state == Qt.Checked)

    def _setup_editor(self):
        global DEV_MODE
        self.editor = QTextEdit()

        if DEV_MODE:
            pass #self.editor.append("READMECHS()")
        else:
            self.message("MWO-Stats Monitor by Captain Jameson aka /u/w0nk0.")
            self.message("Win/Loss counter and Screenshot additions by /u/Krivvan.\n")
            self.message("This app will poll for new match results every %d seconds and display damage stats." % (
                POLL_INTERVAL / 1000))
            self.message("The button on the lower right will save/append account stats to a set of CSV files.")
            self.message("Screenshots will be taken shortly after a win or loss is recognized and moved to the directory specified.")

        #self.editor.setFont(QFont ("Courier", 9))
        self.editor.setStyleSheet("font: 9pt \"Courier\";")
        #self.editor.insertHtml(BITCOIN_HTML)


        return self.editor

    def message(self, txt):
        self.editor.moveCursor(QTextCursor.End)
        self.editor.append(txt)
        self.editor.moveCursor(QTextCursor.End)
        self.editor.ensureCursorVisible()

    def status(self, text):
        if self.statusBar:
            self.statusBar.showMessage(text)
        else:
            self.label.setText(text)

    def _setup_timer(self):
        data_update_timer = QTimer(self)
        self.connect(data_update_timer, SIGNAL("timeout()"), self.data_update)
        self.label.setText("Starting timer")
        data_update_timer.start(self.POLL_INTERVAL)
        # noinspection PyTypeChecker
        QTimer().singleShot(5000, lambda: self.data_update())

        base_update_timer = QTimer(self)
        self.connect(base_update_timer, SIGNAL("timeout()"), self.post_base_results)
        base_update_timer.start(self.POLL_INTERVAL)

        result_poll_timer = QTimer(self)
        self.connect(result_poll_timer, SIGNAL("timeout()"), self.post_results)
        result_poll_timer.start(self.RESULT_POST_INTERVAL)

    def post_results(self):
        results = self.dc.get_new_weapon_results()
        #self.updates+=1
        if results:
            self.updates = 0
            self.poll_start = time()
            self.games += 1
            self.status("New results found!")
            self.editor.moveCursor(QTextCursor.End)
            self.message("\n".join(results))
            #self.sound_notify() # replaced by win/loss sounds
            # noinspection PyTypeChecker
            QTimer().singleShot(500, lambda: self.post_base_results())
        else:
            pass #self.label.setText("No new results found, checked %dx" % self.updates)
    
    def post_base_results(self):
        #print "post_base_results"
        if not self.dc:
            return
        assert (isinstance(self.dc, MWODiffChecker))
        results = self.dc.get_new_base_results() # TODO not properly asynchrounous, dc should post those itself?
        #print("Getting base results")
        if results:
            # Move screenshot and then rename according to results
            QTimer().singleShot(17000, lambda: self.find_and_move_screenshot(results))
            
            self.status("New base results found!")
            self.message(results)
            base_result = self.dc.base_stats_new
            assert (isinstance(base_result, BaseStats))
            if base_result.MatchesPlayed() % self.csv_write_interval == 0:
                self.CSVs()
                self.auto_save_mech_stats_bookmark()
                #self.sound_notify()
                #QTimer().singleShot(1000, lambda: self.data_update())
        else:
            #print "nothing new :("
            #self.label.setText(str(self.dc.get_new_base_results())) # FIXME - Broken
            self.label.setText(str(self.dc.base_stats_old)) # FIXME - resolve at the source!

        starting_stats = self.dc.get_base_stats_session_start()
        if (not self.base_stats_posted) and starting_stats:
            #self.editor.setHtml("<h2>Logged in successfully!<br>"+str(self.dc.new_base)+"</h2><br>")
            #self.editor.setFontPointSize(11)
            wt = self.editor.fontWeight()
            self.editor.setFontWeight(QFont.Bold)
            self.message("\nLogged in successfully!\n\n" + str(starting_stats) + "\n")
            self.editor.setFontWeight(wt)
            #self.editor.setFontPointSize(10)
            self.base_stats_posted = True

    def find_and_move_screenshot(self, results):
        location_directory = self.screenshotLocation
        destination_directory = self.screenshotDestination
        
        if (not os.path.isdir(location_directory) ):
          print "MWO Screenshot directory is incorrect!"
          return
          
        if (not os.path.isdir(destination_directory)):
          print "Destination directory does not exist!"
          return          
        
        screenshot_files = [file for file in glob.glob(os.path.join(location_directory, '*.jpg'))]
        screenshot_files.sort(key=os.path.getmtime)
        latest_screenshot = screenshot_files[-1]
        
        # Just making sure that the screenshot actually came from this game
        if ((time() - os.path.getmtime(latest_screenshot)) > 60):
          print "Screenshot wasn't found!"
          return

        resultsNew = results.translate(None, ',!@#$')
        new_filename = location_directory + "/" + str(int(time())) + " " + resultsNew + ".jpg"
        
        try:
          os.rename(latest_screenshot, new_filename)
          shutil.move(new_filename, destination_directory)
        except:
          print "Failed to rename and move screenshot. Insufficient permissions?"
        
    def onLoginOK(self):
        self.status("Logged in!")
        self.auto_load_mech_stats_bookmark()

    def onLoginFail(self):
        self.message("Login has failed. Please check your credentials.")
        self.message("Re-enable auto-login with the checkbox below when done.")
        self.login_checkbox.setCheckState(Qt.Unchecked)
        self.onLoginCheckbox(Qt.Unchecked)

    def onNewEmail(self, text):
        self.email = text
        self.status("Email set")
        self.login_checkbox.setCheckState(Qt.Unchecked)
        self.onLoginCheckbox(not Qt.Checked)

    def onNewPwd(self, text):
        self.password = text
        self.status("Password set")
        self.login_checkbox.setCheckState(Qt.Unchecked)
        self.onLoginCheckbox(not Qt.Checked)

    def closeEvent(self, e):
        print self, "closing"
        self.settings.setValue('email', encode(self.email))
        self.settings.setValue('password', encode(self.password))
        self.settings.setValue('CSV_INTERVAL', CSV_INTERVAL)
        self.settings.setValue('lastversion', APP_VERSION)
        self.settings.setValue('screenshotLocation', self.screenshotLocation)
        self.settings.setValue('screenshotDestination', self.screenshotDestination)
        self.save_size() #self.parent()
        #print "saving email and pw: %s %s" % (self.email,self.password)
        log = self.editor.toPlainText()
        try:
            log += "\n" + str(self.dc.new_base)
        except:
            pass
        with open("%s.log" % APPNAME, "at") as f:
            # noinspection PyArgumentList
            time_string = QDateTime.toString(QDateTime.currentDateTime())
            f.write("\n*********************************************************\n")
            f.write(time_string)
            f.write("\n*********************************************************\n")
            f.write(log)

        # save mech stats, moved here from mainWindow
        print "Saving fresh mech snapshot!"
        self.dc.threaded_get_page("mech", self.auto_save_mech_stats_bookmark)
        sleep(4)
        e.accept()

        #self.dc.html_thread.stop()
        #self.dc.login_thread.stop()
        #global app
        #app.closeEvent()
        #app.close()
        #del app

        #QThreadPool.globalInstance().close()
        #QThreadPool.globalInstance().closeEvent()
        #del QThreadPool # this throws an Exception, but at least the app closes! :S
        #return True

    def save_size(self, window=None):
        win = window or self
        self.settings.setValue('size', win.size())

    def kill_scraper(self):
        del self.dc
        self.dc = None
        self.status("Invalidating scraper")
        #
        #THIS SHOULD BE IN DC not in HERE
        #
        #del self.browser
        #self.browser = mechanize.Browser()
        #
        #login(self.email,self.password)

    def run_stat_update(self):
        #if self.dc:
        #    self.dc.base_check()
        #    print self.dc.base_stats_old
        #    #return

        self.message("Running status update..")
        self.status("Running status update..")
        try:
            self.message(self.CSVs())
        except AttributeError, e:
            self.message("Status update failed! :(")
            self.message("Wrong credentials maybe?")
            self.message("Error: %s" % str(e))
            self.kill_scraper()
            return
        self.status("Status update complete.")
        self.games = 0

    @staticmethod
    def csv_table(html, filename, account):
        s = bs4.BeautifulSoup(html)
        table = s.find('table')
        rows = table.findAll('tr')
        dt = localtime()
        query_time = "%04d-%02d-%02d %02d:%02d" % (dt.tm_year, dt.tm_mon, dt.tm_mday, dt.tm_hour, dt.tm_min)

        newfile = not os.path.exists(filename + '.csv')
  
        with open(filename + '.csv', 'ab') as f:
            wr = csv.writer(f)
            for r in rows:
                hdrs = ["# " + c.text for c in r.findAll('th')]
                tds = [str(c.text).translate(None, '\n\r') for c in r.findAll('td')]
                if len(hdrs):
                    cells = hdrs
                    cells.append("Time")
                    cells.append("account")
                    if newfile:
                        wr.writerow(cells)
                else:
                    cells = tds
                    cells.append(query_time)
                    cells.append(account)
                    wr.writerow(cells)

        return len(rows)

    def CSVs(self):
        if not self.dc:
            self.status("Not logged in yet, wait a few seconds please.")
            return "Not logged in yet, wait a few seconds please."

        self.message("Collecting and saving stats to CSV files..")

        self.dc.check()
        sleep(2)

        result = ""
        account = str(self.email)[:self.email.find("@")]

        for t in ['mech', 'base', 'weapon', 'mode', 'map']:
            filename = account + "-" + t
            self.status("Getting %s stats,." % t)
            html = self.dc.get_page(t)
            print "Type: %-10s Rows: %4d" % (t, self.csv_table(html, filename, account))
            result += "<br>" + "Type: %-10s Rows: %4d" % (t, self.csv_table(html, filename, account))
            #print ("DONE!")
        return result

    @staticmethod
    def sound_notify():
        try:
            snd = QSound("spacey-confirm.wav")
            snd.play()
        except:
            print "Couldn't play sound"

    def new_credentials(self):
        if not self.new_credentials_set:
            self.status("New credentials!")
            self.editor.setText("New credentials received. Check the 'Log In?' box to use them!")
            self.message(
                "\nIf no stats show up, please double-check your credentials on mwomercs.com and restart the app.")

            # noinspection PyTypeChecker
            QTimer().singleShot(5000, lambda: self._setup_dc())
        self.new_credentials_set = True


    def _setup_dc(self):
        self.status('Setting up DC')
        self.dc = MWODiffChecker(self.email, self.password)
        self.dc.sigStatus.connect(self.status)
        self.dc.allow_login(self.login_checkbox.isChecked())
        self.dc.sigLoginFail.connect(self.onLoginFail)
        self.dc.sigLoginOK.connect(self.onLoginOK)
        self.dc.sigMessage.connect(self.message)

        self.status('Checking base stats')
        # noinspection PyTypeChecker
        QTimer().singleShot(5000, lambda: self.dc.base_check())
        # noinspection PyTypeChecker
        QTimer().singleShot(7500, lambda: self.post_base_results())#TODO - add base stats win%,.. INSTEAD
        # TODO - that will be in dc.new_base I think?

        self.new_credentials_set = False

        #self.dc.base_check()
        #self.message(str(self.dc.get_new_base_results())) #TODO - add base stats win%,.. INSTEAD

    def dc_is_ok(self):
        if not self.dc:
            self.status("Initializing scraper")
            if self.password_is_set:
                self._setup_dc()
            else:
                self.label.setText('No Credentials :(')
                return False
        return True


    def data_update(self):

        if not self.dc_is_ok():
            return
        self.updates += 1
        #self.setStatusTip("Updates since last result: %d" % self.updates)
        #diff=self.dc.print_stat_diffs_html()

        #self.status("data_update() calling dc.check()")
        self.updates += 1
        self.status("Stats poll #%d" % self.updates)

        if not self.dc.logged_in:
            self.status("NOT LOGGED IN!")
            self.dc.threaded_login()
            return

        from  time import sleep
        self.dc.base_check()
        #sleep(0.4)
        self.dc.check()

        t_diff = int(time() - self.poll_start)
        secs = t_diff % 60
        mins = int(t_diff / 60)
        #self.sigStatus.emit("No new results for %d:%02d .." % (mins, secs))
        self.status("No new results for %d:%02d .." % (mins, secs))

        return

    def show_session_stats(self):
        # TODO flesh this out
        assert ( isinstance(self.dc, MWODiffChecker))
        self.message("Session stats so far: " + self.dc.session_base_diff_str() + "\n")

    def get_mech_stats(self):
        if self.dc:
            filename = None
            #alltext=self.editor.toPlainText()
            #
            # if False: # OLD 07a DEVMODE STUFF
            #     if "READMECHS(" in alltext:
            #         print "Magic found!"
            #         filename=alltext.split("READMECHS(")[1]
            #         filename=filename.split(")")[0]
            #         print "filename:",filename
            #         self.dc.mech_stats_session_start=None
            #     else:
            #         if DEV_MODE:
            #             self.message("use READMECHS/WRITEMECHs(filename) to read/write a file")
            #
            #     if DEV_MODE:
            #         if "WRITEMECHS(" in alltext:
            #             filename=alltext.split("WRITEMECHS(")[1]
            #             filename=filename.split(")")[0]
            #             self.message("WRITEMECHS()found, writing to %s" % filename)
            #             with open(filename,"wt") as f:
            #                 f.write(self.dc.mech_stats.html)
            #             self.message("Success!")
            #             return
            #
            #         if "READMECHS()" in alltext:
            #             # noinspection PyCallByClass
            #             filename, _ = QFileDialog().getOpenFileName(self, 'Open mech html file','.',"*.htm*")

            self.dc.mech_stats_load_or_query(filename) # filename=None will query from mwomercs

    def mech_session_report(self):
        if self.dc:
            self.dc.mech_stats_load_or_query(show_report = True)
            #QTimer().singleShot(4000, lambda: self.dc.mech_session_report())

    def auto_load_mech_stats_bookmark(self, days_offset=-1):
        if not self.dc:
            print("DC not ready to load mech stats :(")
            return

        filename = mech_snapshot_filename(days_offset)
        print "Auto-loading mech stats from ", filename
        self.load_mechstats_session_base(filename)

    def auto_save_mech_stats_bookmark(self, html=None): # TODO test if this works to read as session base stats
        filename = mech_snapshot_filename(0)
        print "Saving mech stats to ", filename
        if html: print "(From fresh html snapshot!)"
        self.save_mech_stats_bookmark(filename, html)

    def save_mech_stats_bookmark(self, filename=None, html = None): # TODO test if this works to read as session base stats
        if not filename:
            filename, _ = QFileDialog().getSaveFileName(self, 'Mech data html file', '.', "*.html")
        if not filename:
            self.message("No filename given, not saving anything")
            return

        if html:
            try:
                os.unlink(filename) 
            except:
                pass
            with open(filename,"wt") as f:
                f.write(html)
            return

        dc = self.dc
        assert (isinstance(dc, MWODiffChecker))
        dc.mech_stats.write_to_file(filename)
        self.message("Mech stats html saved for later re-import")

    def load_mechstats_session_base(self, filename=None):
        if not filename:
            f_name, _ = QFileDialog().getOpenFileName(self, 'Open mech html file', '.', "*.htm*")
        else:
            f_name = filename
        if f_name:
            self.dc.mech_stats_load_or_query(f_name,
                                             reset_session=True) # NEXT TEST THIS! esp. if it resets sesssion_base_stats
        else:
            self.message("No file selected, aborting")


    def get_tournament_html(self):
        tourney_url = "http://mwomercs.com/tournaments"
        getter = HtmlOpenThread(self.dc.browser,None,self.receive_tournament,10,tourney_url)
        getter.autoDelete()
        getter.setAutoDelete(True)
        QThreadPool.globalInstance().start(getter)

    def receive_tournament(self,html):
        # can't open webview here, it's called from the html getter thread!
        self.tourney_html = html
        #print "Got tourney results"
        #print "Tourney result timer set to show"
        with open("tournament-standings.html","wt") as f:
            f.write(html.replace("//static","http://static"))
        self.sigShowTournament.emit()

    def show_tournament_view(self):
        if not self.tourney_html:
            return

        html = self.tourney_html

        import re
        p = re.compile(ur'<h3 style="text-align: center; background-color: #000;">(.*?)<')
        re_result='(<table class="table table-striped">.*?</table>)'

        result=re.search(p, html)
        if not result:
            result=re.search(re_result,html.replace("\n",""))

        text = "Error trying to parse the Halloween 2014 event :("
        try:
            text = result.group(1)
        except IndexError:
            text = "No Halloween 2014 tournament results found :("
        except AttributeError:
            print "Something went wrong with html:" + html

        if "<" in text:
            text=text.replace("120","180")
            text=text.replace('"50','"90')
            self.editor.moveCursor(QTextCursor.End)

            message = "<table>"
            entries = []
            for item in re.findall("(<tr>.*?</tr>)",text,re.MULTILINE + re.DOTALL):
                entries.append(item)
            #print(entries)
            message += entries[0]
            message += " ".join(entries[-5:])
            message += "</table>"
            self.editor.insertHtml("<p>"+message+"</p>")
        else:
            self.message("\nTournament info:\n"+text+"\n")

        if "INTO" in text:
            snd = QSound("cheer.wav")
            snd.play()

        return

        #     regex=re.compile('data-gameid="(.*?)">REACH')
        #     match=regex.search(text)
        #     gameid = match.group(1)
        #     print "Found gameid", gameid
        #     # params = {"gameid": str(gameid)}
        #     # import urllib
        #     # data = urllib.urlencode(params)
        #     # url = "http://mwomercs.com/tournaments"
        #     # #req = mechanize.Request(url,data)
        #     # response = self.dc.browser.open(url , data = data)
        #     # print response.read()
        #     html = self.requests_game_submitter(gameid)
        #     self.dc.threaded_login()
        #     try:
        #         #os.unlink("_redeem.html")
        #         html = html.encode('ascii','replace')
        #         with open("_redeem.html","wt") as f:
        #             html = html.replace('"/','"http://mwomercs.com/')
        #             html = html.replace("mwomercs.com//static","static")
        #             f.write(html)
        #         regex=re.compile('">(.*?)<\/td',re.M + re.DOTALL)
        #         for s  in regex.findall(html):
        #             #s = s.encode('ascii',errors='replace')
        #             print s
        #
        #     except Exception,e:
        #         print "Couldn't print response html"
        #         print "## ERROR:",e,e.message
        #     print "Logging in again"

    def requests_game_submitter(self,gameid):
        """
        This seems to not be working, unfortunately. No clue how the do the redemption with jQuery
        :param gameid:
        :return:
        """
        import requests
        s=requests.Session()
        emp = { 'email':self.email, 'password': self.password}
        log=s.post("http://mwomercs.com/do/login",emp)
        game = {'gameid' : str(gameid)}
        req = requests.Request('POST',"http://mwomercs.com/tournaments", data = game)
        #log=s.post("http://mwomercs.com/tournaments",game)
        prep = req.prepare()
        log = s.send(prep)
        return log.text

    def pre_halloween_2014_show_tournament_view(self):
        if not self.tourney_html:
            return

        if not self.pilot_name:
            prompt = 'Enter your pilot name to look for (case matters!):'
            text, ok = QInputDialog.getText(self, 'Pilot name', prompt)
            self.pilot_name = text

        pilots = self.pilot_name.split(",")
        print "Pilots:", pilots

        ana = TourneyAnalyzer(pilots)
        ana.html = self.tourney_html
        text = ana.analyze()

        self.message("\nTourney Standings:\n"+text)

        #from PySide.QtWebKit import QWebView
        #self.tourney_view = QWebView()
        #self.tourney_view.setHtml(self.mainWindow.tourney_html)
        #self.tourney_view.setWindowTitle("Tournament standings")
        #self.tourney_view.resize(900,980)
        #self.mainWindow.tourney_html = None
        #self.tourney_view.show()


class MWOMonitorWindow(QMainWindow):
    def __init__(self, parent=None):
        super(MWOMonitorWindow, self).__init__(parent)
        self.mainWindow = MainWidget(self)
        self.setWindowTitle(APPNAME + " " + APP_VERSION)
        self.setupMenus()

        self.setCentralWidget(self.mainWindow)

        self.mainWindow.statusBar = self.statusBar()
        self.mainWindow.initialize()




    # noinspection PyPep8Naming
    def setupMenus(self):
        exitAction = QAction(QIcon('exit.png'), '&Exit', self)
        exitAction.setShortcut('Ctrl+Q')
        exitAction.setStatusTip('Exit application')
        exitAction.triggered.connect(self.close)

        clearAction = QAction(QIcon(), "&Clear", self)
        clearAction.setShortcut('Ctrl+W')
        clearAction.setStatusTip("Clear contents")
        clearAction.triggered.connect(self.clear_editor)

        checkUpdateAction = QAction(QIcon(), "Check for &Updates", self)
        checkUpdateAction.setStatusTip("Opens a browser window")
        checkUpdateAction.triggered.connect(self.open_update_window)

        donateAction = QAction(QIcon(), "Donate", self)
        donateAction.triggered.connect(self.show_donate_window)

        filemenu = self.menuBar().addMenu("&File")
        filemenu.addAction(clearAction)
        filemenu.addAction(checkUpdateAction)
        filemenu.addAction(donateAction)
        filemenu.addSeparator()
        filemenu.addAction(exitAction)

        ## SESSION STATS
        session_stats_menu = self.menuBar().addMenu("&Session Stats")

        sessionStatsAction = QAction(QIcon(), "Overall performance", self)
        sessionStatsAction.setStatusTip("C-Bills, XP, K/D since program launch")
        sessionStatsAction.triggered.connect(self.show_session_stats)
        session_stats_menu.addAction(sessionStatsAction)

        mechReport = QAction(QIcon(), "Mech Report", self)
        mechReport.triggered.connect(self.mainWindow.mech_session_report)
        session_stats_menu.addAction(mechReport)

        session_stats_menu.addSeparator()

        getMechs = QAction(QIcon(), "Refresh mech stats", self)
        getMechs.setStatusTip("Gets the current Mech stats from mwomercs.com")
        getMechs.triggered.connect(self.mainWindow.get_mech_stats)
        #session_stats_menu.addAction(getMechs)

        loadMechStatsAction = QAction(QIcon(), "Load snapshot as session base", self)
        loadMechStatsAction.setStatusTip(
            "Loads a previously saved bookmark as a baseline - to give reports on a 'since then' basis")
        loadMechStatsAction.triggered.connect(self.load_mech_stats)
        session_stats_menu.addAction(loadMechStatsAction)

        saveMechStatsAction = QAction(QIcon(), "Save Mech stats snapshot", self)
        saveMechStatsAction.setStatusTip("Saves current mech stats to as a session baseline")
        saveMechStatsAction.triggered.connect(self.save_mech_stats)
        session_stats_menu.addAction(saveMechStatsAction)

        ## OVERALL STATS
        longterm_menu = self.menuBar().addMenu("&Long-Term Stats")

        dpgAction = QAction(QIcon(), "Damage per &Game for all Mechs", self)
        dpgAction.triggered.connect(self.show_dpg_stats_window)
        longterm_menu.addAction(dpgAction)

        dotAction = QAction(QIcon(), "Stats over &Time for one Mech", self)
        dotAction.triggered.connect(self.show_mech_over_time_window)
        longterm_menu.addAction(dotAction)


        ## special

        special_menu = self.menuBar().addMenu("Events")

        tournamentAction = QAction(QIcon(),"Check Halloween 2014 event",self)
        tournamentAction.triggered.connect(self.get_tournament_html)
        special_menu.addAction(tournamentAction)

        tournamentAction = QAction(QIcon(),"Redeem Halloween items!",self)
        tournamentAction.triggered.connect(self.halloween_redeem)
        special_menu.addAction(tournamentAction)

        self.checkChallengeMenuItem = QAction(QIcon(), "Check for challenge results", self)
        #checkChallengeAction.triggered.connect
        self.checkChallengeMenuItem.triggered.connect(self.challengeActionTrigger)
        self.checkChallengeMenuItem.setCheckable(True)
        special_menu.addAction(self.checkChallengeMenuItem)

        #if not DEV_MODE: #TODO remove for release
        #    return
        return

    def challengeActionTrigger(self, checked=False):
        if self.mainWindow.dc:
            dc = self.mainWindow.dc
            assert (isinstance(dc, MWODiffChecker))
            value = self.checkChallengeMenuItem.isChecked()
            dc.check_challenge = value
            print "Setting mW.dc.check_challenge to %s" % value
            if value:
                self.mainWindow.status("Challenge reporting: ON.")
            else:
                self.mainWindow.status("Challenge reporting disabled-")


    @staticmethod
    def show_donate_window():
        #w = self.donate_win = DonateWebView()
        #w.show()
        write_html("donate.html")
        # noinspection PyTypeChecker
        QDesktopServices().openUrl("donate.html")

    def clear_editor(self):
        self.mainWindow.editor.setText("")

    def closeEvent(self, event):
        print "main win close()"
        #self.mainWindow.save_size(self)
        #self.mainWindow.auto_save_mech_stats_bookmark()
        self.mainWindow.close()
        print "main Window closed."
        event.accept()

    @staticmethod
    def open_update_window():
        # noinspection PyTypeChecker
        win = QDesktopServices().openUrl(UPDATE_URL)
        return win

    def get_mech_csv_name(self):
        result = ""
        try:
            result = self.mainWindow.email_field.text().split("@")[0] + "-mech.csv"
        except:
            print "Failed to get CSV file name"
        return result


    def show_dpg_stats_window(self):
        if not os.path.exists("mechs.sqlite"):
            self.mainWindow.editor.append("\n\nThis might take a minute when running the first time, hang on!\n")
        else:
            self.mainWindow.editor.append("\n\nUpdating database in 'mechs.sqlite'.\n")
            self.mainWindow.editor.append("If you switch accounts, delete that file in explorer to re-read from CSVs.\n")
        #self.mainWindow.editor.append("You need to have saved CSV stats for this to work")
        #self.mainWindow.editor.append(
        #    "(the program will save those every %d games on its own)" % self.mainWindow.csv_write_interval)
        # noinspection PyTypeChecker
        QTimer().singleShot(3000, lambda: self._show_dpg_stats_window())

    def _show_dpg_stats_window(self):
        file_name = self.get_mech_csv_name()
        print "making mech stats for file", file_name
        mechs, _, _ = c2p.make_peewee_db()
        c2p.fill_peewee_mechs(file_name)
        dlg = c2p.CurrentStatSnapshotDialog(model=c2p.MechStats)
        dlg.exec_()


    def show_mech_over_time_window(self):
        self.mainWindow.editor.append("THIS MIGHT TAKE A MOMENT, HANG ON!\n")
        self.mainWindow.editor.append("You need to have saved CSV stats for this to work")
        self.mainWindow.editor.append("(the program will save those every 20 games on its own)")
        # noinspection PyTypeChecker
        QTimer().singleShot(1000, lambda: self._show_mech_over_time_window())

    def _show_mech_over_time_window(self):
        file_name = self.get_mech_csv_name()
        print "making mech stats for file", file_name
        mechs, _, _ = c2p.make_peewee_db()
        c2p.fill_peewee_mechs(file_name)
        dlg = c2p.MechStatsDialog(model=c2p.MechStats)
        dlg.exec_()

    def show_session_stats(self):
        self.mainWindow.show_session_stats()

    def load_mech_stats(self):
        self.mainWindow.load_mechstats_session_base()

    def save_mech_stats(self):
        self.mainWindow.save_mech_stats_bookmark()

    def get_tournament_html(self):
        self.mainWindow.get_tournament_html()

    def halloween_redeem(self):
        #QDesktopServices().openUrl("https://mwomercs.com/login?return=/tournaments")
        self.w = EventQWeb()
        self.w.show()
        self.w.startup(self.mainWindow.email, self.mainWindow.password)
        self.w.closeSignal.connect(self.mainWindow.dc.threaded_login)
        self.mainWindow.dc.logged_in = False
        #QTimer().singleShot(10000,lambda: self.mainWindow.dc.threaded_login())


############################

if __name__ == "__main__":
    import sys
    import os

    if os.path.exists("DEVMODE"):
        DEV_MODE = True

    app = QApplication(argv)


    #w=MyWindow(a)
    w = MWOMonitorWindow()
    w.show()

    app.exec_()
    del w
    del app
    sys.exit()

#############################

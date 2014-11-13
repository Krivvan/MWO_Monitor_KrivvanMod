__author__ = 'nico'

MIN_MATCHES = 5-1

from peewee import *
from csv import DictReader, reader

db_proxy = Proxy() # needed for peewee

def setupPeeweeDB(filename=None):
    if not filename:
        filename = "mechs.sqlite"
    db_file="" + (filename or ":memory:")
    return SqliteDatabase(db_file)


def process_key(k):
    assert (isinstance(k,str))
    s=k.replace('#','')
    s=s.replace(' ','_')
    return s

def process_value(v):
    v=v.replace(",", "")#.replace(" ","")
    if "/" in v:
        return v.split("/")
    else:
        return v


# noinspection PyUnresolvedReferences
def makeFieldNames(csvfile):
    return [(field,field_type)]

class MechStats(Model):
    Mech = CharField(index=True)
    Time = DateTimeField()
    Wins = IntegerField(null=True)
    Losses = IntegerField(null=True)
    Matches = BigIntegerField()
    Kills = IntegerField(null=True)
    Deaths = IntegerField(null=True)
    DamageDone = FloatField(default=0.0)
    ExpTotal = FloatField()
    #DPG = FloatField(null=True)
    ExpPG = FloatField(null=True)
    Account = CharField()
    TimePlayed = TimeField(null=True)
    WLRatio = FloatField(null=True)
    KDRatio = FloatField(null=True)

    @property
    def DPG(self):
        return self.DamageDone / (1.0+self.Matches)

    def __str__(self):
        wins = self.Wins or 0
        matches = self.Matches or 0
        dmg = self.DamageDone or 0
        wl=(0.01+wins) / (0.01+matches) *100
        dpg=self.DPG or (0.01+dmg) / (0.01+matches)
        params = (self.Mech[:16], matches, wins,wl, self.Kills or 0, self.Deaths or 0, dpg)
        return "%-16s: %4d Games, %4d Wins (%4.1f%%), %3d/%3d K/D, %3.0f DPG" % params

    class Meta:
        database = db_proxy
        order_by = ["Time","Mech"]
        indexes = (
            # create a unique on from/to/date
            (('Mech', 'Account', 'Time'), True)
        )

def make_peewee_db(filename=None):
    """returns (Mechs, Weapons, Base) tables tuple"""
    global db_proxy
    db=setupPeeweeDB(filename)
    try:
        db_proxy.initialize(db)
    except AttributeError:
        print "Something went wrong, db=",db
        raise
    try:
        mechs=db.create_table(MechStats)
    except:
        print "Table mechs exists."
        mechs=MechStats
    return mechs,None,None

def make_mech_mapper(filename):
    """ returns dict ( field_name->CSV_field_name )
    """
    with open(filename, "rt") as f:
        rd=reader(f)
        for row in rd:
            fields=['Mech','Matches','Wins','Losses','WLRatio','Kills','Deaths','KDRatio']
            fields.extend(['DamageDone','ExpTotal','TimePlayed','Time','Account'])
            #d=zip(fields,[process_key(k) for k in row])
            d=zip(fields,[k for k in row])
            return dict(d)

# noinspection PyPep8Naming
def fill_peewee_mechs(filename):
    kd = make_mech_mapper(filename) # key_dict = ..
    #print "\nKEYDICT:",kd

    try:
        max_time = get_max_time()
        print "Previous max_time:", max_time
    except:
        max_time = None

    with (open(filename, "rt")) as f:
        dictreader = DictReader(f)
        for row in dictreader:

            if row[kd['Time']] < max_time:
                #print ".",
                continue

            for key in row.keys():
                row[key]=process_value(row[key])

            # Check if there are header rows somewhere in the data, if so skip the row
            skip_row = False
            for val in row.values():
                if "#" in val:
                    skip_row  = True

            if skip_row:
                continue

            # Warning, the values won't coerce into their types before they are save()d!
            m=MechStats()
            m.Mech=row[kd['Mech']]
            m.Account=row[kd['Account']]
            m.Time=row[kd['Time']]
            m.Matches=row[kd['Matches']] or 0
            m.DamageDone = row[kd['DamageDone']] or 0
            m.Wins = row[kd['Wins']] or 0
            m.ExpTotal = row[kd['ExpTotal']] or 0
            m.Kills = row[kd["Kills"]] or 0
            m.Deaths = row[kd["Deaths"]] or 0

            m.save()
            m=m.get() # this coerces values into the right type!

            #m.DPG = (0.01+m.DamageDone) / (0.01+m.Matches)
            m.ExpPG = (0.01+m.ExpTotal) / (0.01+m.Matches)

            m.save()
            #print m.DPG
            #key_str = "(" + " , ".join(keys) + ")"
            #val_str = "(" + " , ".join(values) + ")"
            #insert_str = "INSERT INTO t %s VALUES %s;" % (key_str, val_str)
            #for key,value in row.items():
            #    insert_str = "INSERT INTO t ('%s') VALUES ('%s');" % (key,value)
            #    #print "inserting %s -> %s" % (key,row[key])
            #cursor.execute(insert_str)
            #connection.commit()

def get_max_time():
    record = MechStats.select().order_by(MechStats.Time.desc()).get()
    max_time = record.Time
    return max_time

def get_latest_stats(time_filter=None):
    if not time_filter:
        time_filter=MechStats.select().group_by(MechStats.Time)\
            .order_by(MechStats.Time).desc()\
            .limit(1)
    many_matches=MechStats.select().where(
        MechStats.Matches > 20, MechStats.Time == time_filter).order_by(
        MechStats.Matches).asc()
    return many_matches

def print_stats_by_matches(result_set):
    all_hits={}
    for hit in result_set:
        assert isinstance(hit,MechStats)
        all_hits[float(hit.DPG)]=str(hit)
        if not str(hit) in all_hits:
            print hit

def stats_by_dpg(result_set):
    all_hits={}
    for hit in result_set:
        assert isinstance(hit,MechStats)
        all_hits[float(hit.DPG)]=str(hit)

    i=all_hits.items()
    i.sort()
    results=[]
    for v in i:
        results.append(str(v[1]))
        #print v[1]
    return "\n".join(results)


def mech_stats_by_time(mech,min_match_increment=3):
    result=MechStats.select().where(MechStats.Mech == mech)
    report=[]
    prev_Matches=0
    for r in result:
        if r.Matches > prev_Matches+ min_match_increment:
            prev_Matches = r.Matches
            report.append(str(r.Time)+" : "+str(r))
    return report


#latest=get_max_time()
#print stats_by_dpg(get_latest_stats(latest))

from PySide.QtGui import *

class MechSelectDlg(QDialog):
    def __init__(self, items=None, model=None):
        super(MechSelectDlg,self).__init__()
        self.combo = QComboBox(self)
        self.combo.activated[str].connect(self.onSelected)
        self.selected = None

        btn_box=QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.onAccept)
        btn_box.rejected.connect(self.onReject)

        self.layout = layout=QVBoxLayout()
        self.label=QLabel("Select a mech!")
        layout.addWidget(self.label)
        layout.addWidget(self.combo,2)
        layout.addWidget(btn_box,1)
        self.setLayout(layout)
        #self.combo.show()
        self.selection = None

        if not items:
            if not model:
                raise SystemExit, "Need at least a model if I don't get any items!"
            items=self.get_items_from_model(model)

        self.fill_items(items)

    def get_items_from_model(self,model):
        result=model.select().where(model.Matches >= MIN_MATCHES).group_by(model.Mech)
        mechs=[item.Mech for item in result]
        return mechs

    def fill_items(self, items):
        self.combo.addItem("SELECT A MECH")
        items=[x for x in set(items)]
        items.sort()
        for item in items:
            self.combo.addItem(item)

    def onSelected(self,item):
        self.selected=item

    def onAccept(self):
        self.selection=self.selected
        self.done(1)
        #self.close()

    def onReject(self):
        self.selection=None
        self.done(0)
        #self.close()

    def result(self, *args, **kwargs):
        return self.selection

    #def accepted(self):
    #    self.close()

class MechStatsDialog(MechSelectDlg):
    def __init__(self,items=None, model=None):
        super(MechStatsDialog,self).__init__(items=items, model=model)

        self.resultWidget = QListWidget()
        self.resultWidget.resize(650,450)

        self.setWindowTitle("Long-term Mech statistics")
        self.resize(700,500)
        self.resultWidget.setFont(QFont("Courier"))
        self.layout.addWidget(self.resultWidget)

    def onAccept(self):
        super(MechStatsDialog,self).onAccept()

    def make_result_query(self,item):
        mech= item or self.selected
        query_result = mech_stats_by_time(mech)
        return query_result

    def fill_results(self, item=None):
        query_result=self.make_result_query(item)
        separator = "----------------------------------"
        stats=[separator]
        stats.extend(query_result)
        stats.append(separator)
        self.resultWidget.addItems(stats)

    def onSelected(self,item):
        super(MechStatsDialog,self).onSelected(item)
        self.fill_results(item)


class CurrentStatSnapshotDialog(MechStatsDialog):
    def __init__(self,items=None, model=None):
        self.model=model
        super(CurrentStatSnapshotDialog,self).__init__(items,model)
        self.label.setText("Select a snapshot time")

    def fill_items(self, items):
        assert isinstance(items, list)
        self.combo.addItem("SELECT A SNAPSHOT TIME")
        self.combo.addItems(items)

    def get_items_from_model(self,model):
        result=model.select().group_by(model.Time).order_by(model.Time).desc()
        return [x.Time for x in result[::-1]]

    def make_result_query(self,item):
        item = item or self.selected
        model = self.model or MechStats
        qr = model.select().where((model.Time == item) & (model.Matches >= MIN_MATCHES) )\
            .group_by(model.Mech).order_by(model.Matches)
        result= [(r.DPG , r) for r in qr]
        result.sort()
        return [str(r[1].Time)+" : "+str(r[1]) for r in result]

def test():
    app = QApplication([])

    _, _ , _ = make_peewee_db()
    fill_peewee_mechs("eigenhandel-mech.csv")

    #mechs=[item.Mech for item in get_latest_stats()]

    #mechs=MechStats.select().group_by(MechStats.Mech)

    #dlg=MechSelectDlg(mechs)
    #print "exce:",dlg.exec_()
    #print "SELECTED",dlg.selection
    #mech=dlg.selection
    #print "\n".join(mech_stats_by_time(mech))
    #del dlg
    dlg=MechStatsDialog(model=MechStats)
    dlg.exec_()
    dlg2 = CurrentStatSnapshotDialog(model=MechStats)
    dlg2.exec_()
    import sys
    app.exec_()
    del dlg
    del app
    sys.exit()



if __name__ == "__main__":
    test()

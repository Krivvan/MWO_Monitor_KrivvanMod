__author__ = 'nico'

class TourneyAnalyzer(object):

    def __init__(self, filter_list=[]):
        self.html = None
        self.filter = filter_list

    def read_html(self, filename= None):
        fn = filename
        try:
            if not fn:
                import urllib2
                f= urllib2.urlopen("http://mwomercs.com/tournaments")
                self.html = f.read()
            else:
                with open(fn,"rt") as f:
                    self.html = f.read()
        except Exception, e:
            print "Couldn't read html"
            print e

    def analyze(self):
        if not self.html:
            return ""

        import re
        names_re = re.compile('24"> (.*?)<')
        place_re = re.compile("<td>(\d+)</td>")
        scores_re = re.compile('nt">(.*?)<')
        mech_re = re.compile('"textCenter">(.*?)<')

        mech = "NONE"
        place = 0
        name = None
        score = 0

        result = ""

        for line in self.html.split("\n"):
            mechs = mech_re.findall(line)
            places = place_re.findall(line)
            names = names_re.findall(line)
            scores = scores_re.findall(line)

            if len(mechs):
                mech = mechs[0]

            if len(places):
                place = places[0]

            if len(names):
                name = names[0]

            if len(scores) and name:
                score = scores[0].replace(",","")
                if not self.filter or name in self.filter:
                    res = "%-20s - #%3s: %22s %6s points" % (mech, place, name, score)
                    result += "\n" + res
                    print res
                name = None

        return result

    def analyze_new(self, html = None):
        import re

        h = html or self.html

        if not h:
            print "No html :("
            return

        h = h.replace("\n","")
        h = h.replace("\r","")

        rank=re.compile('(<tr class="yourRankRow">.*?<\/tr>)', re.IGNORECASE+ re.MULTILINE)

        rows = rank.findall(h)
        for r in rows:
            print r

        #for i in range(len(names)):
        #    print i, names[i], "sc: ", scores[i]

if __name__ == "__main__":
    a = TourneyAnalyzer([])
    a.read_html()

    a.analyze()
    a.analyze_new()




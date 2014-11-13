__author__ = 'nico'

EVENT_URL = "https://mwomercs.com/login?return=/tournaments"

js = """
var gameid = $(this).data('gameid');

			$.post('/tournaments', {gameid: gameid}, function(data) {

				if (data.success)
				{
					$('.row_'+gameid).text(data.type + ': ' + data.prize);
					$('.reachButton').attr('disabled', false);
				}
				else
				{
					alert('There was an error! Please try again.');
					location.reload();
				}

			});
"""

from PySide import QtWebKit
from PySide.QtGui import *
from PySide.QtCore import *


class EventQWeb(QtWebKit.QWebView):
    closeSignal = Signal()

    def __init__(self, parent=None):
        super(EventQWeb, self).__init__(parent)
        self.setFixedWidth(1100)

    # def show(self, *args, **kwargs):
    #    print "showing"
    #    super(EventQWeb,self).show(*args,**kwargs)
    #    self.startup(None,"eigenhandel@gmail.com","14krieger14")

    def startup(self, email, password, url=None):
        self.email = email
        self.password = password
        print "Starting"
        url = url or EVENT_URL
        self.load(url)
        self.loadFinished.connect(self.fillform)

    def fillform(self, email=None, password=None):
        email = self.email
        password = self.password
        doc = self.page().mainFrame().documentElement()
        emailfield = doc.findFirst("input[id=email]")
        passwd_field = doc.findFirst("input[id=password]")
        #emailfield.setAttribute("value", email)
        emailfield.evaluateJavaScript("this.value = '%s'" % email)
        passwd_field.setAttribute("value", password)
        passwd_field.evaluateJavaScript("this.value = '%s'" % password)

        button = doc.findFirst("button")
        print button

        self.loadFinished.connect(self.reachintobag)
        button.evaluateJavaScript("this.click()")

    def reachintobag(self):
        self.loadFinished.disconnect()
        #print "Redeeming"
        doc = self.page().mainFrame().documentElement()
        sz = self.page().mainFrame().contentsSize()
        #print "Size:", sz
        sz = QPoint(sz.width(), sz.height() - 1200)
        #print "Size:", sz

        self.page().mainFrame().setScrollPosition(sz)
        doc = self.page().mainFrame().documentElement()
        links = doc.findAll("a")
        btn = None
        for link in links:
            if "data-gameid" in link.attributeNames():
                btn = link

        if not btn:
            print "No redeem button found"
            return

        print btn
        gameid = 0
        for a in btn.attributeNames():
            attr = btn.attribute(a)
            print a, attr
            if "gameid" in a:
                gameid = attr

                print "click 1"
                btn.evaluateJavaScript("this.click()")

                print "JS"
                btn.evaluateJavaScript(js)



    def close(self, e):
        print "Closing Event web view"
        self.closeSignal.emit()
        e.accept()


if __name__ == "__main__":
    import sys

    app = QApplication([])
    w = EventQWeb()
    w.show()
    w.startup("example@gmail.com", "notarealpassword")
    import time

    sys.exit(app.exec_())


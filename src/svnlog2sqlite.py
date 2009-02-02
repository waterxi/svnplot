'''
python script to convert the Subversion log into an sqlite database
The idea is to use the generated SQLite database as input to Matplot lib for
creating various graphs and analysis. The graphs are inspired from graphs
generated by StatSVN/StatCVS.
--- Nitin Bhide (nitinbhide@gmail.com)

Part of 'svnplot' project
Available on google code at http://code.google.com/p/svnplot/
Licensed under the 'New BSD License'

To use, copy the file in Python 'site-packages' directory. Setup is not available
yet.
'''

import svnlogiter
import datetime
import sqlite3
import sys
import logging

class SVNLog2Sqlite:
    def __init__(self, svnrepopath, sqlitedbpath):
        self.svnclient = svnlogiter.SVNLogClient(svnrepopath)
        self.dbpath =sqlitedbpath
        self.dbcon =None
        
    def convert(self, bUpdLineCount=True, maxtrycount=3):
        #First check if this a full conversion or a partial conversion
        self.initdb()
        self.CreateTables()
        for trycount in range(0, maxtrycount):
            try:
                laststoredrev = self.getLastStoredRev()
                headrev = self.svnclient.getHeadRevNo()    
                self.ConvertRevs(laststoredrev, headrev, bUpdLineCount, maxtrycount)
            except Exception, expinst:
                logging.error("Error %s" % expinst)
                print "Error %s" % expinst                
                print "Trying again (%d)" % (trycount+1)
            finally:                        
                self.dbcon.commit()
                
        self.closedb()
        
    def initdb(self):
        self.dbcon = sqlite3.connect(self.dbpath, detect_types=sqlite3.PARSE_DECLTYPES|sqlite3.PARSE_COLNAMES)
        #self.dbcon.row_factory = sqlite3.Row

    def closedb(self):
        self.dbcon.commit()
        self.dbcon.close()
        
    def getLastStoredRev(self):
        cur = self.dbcon.cursor()
        cur.execute("select max(revno) from svnlog")
        lastStoreRev = 0
        
        row = cur.fetchone()
        if( row != None and len(row) > 0 and row[0] != None):
            lastStoreRev = int(row[0])        
        return(lastStoreRev)
               
    def ConvertRevs(self, laststoredrev, headrev, bUpdLineCount, maxtrycount=3):
        if( laststoredrev < headrev):            
            cur = self.dbcon.cursor()
            svnloglist = svnlogiter.SVNRevLogIter(self.svnclient, laststoredrev+1, headrev)
            revcount = 0
            bChkIfDir = bUpdLineCount
            lc_updated = 'N'
            if( bUpdLineCount == True):
                lc_updated = 'Y'
            for revlog in svnloglist:
                logging.debug("converting revision %d" % revlog.revno)
##                logging.debug("Revision author:%s" % revlog.author)
##                logging.debug("Revision date:%s" % revlog.date)
##                logging.debug("Revision msg:%s" % revlog.message)
                revcount = revcount+1
                addedfiles, changedfiles, deletedfiles = revlog.changedFileCount(bChkIfDir)
                cur.execute("INSERT into SVNLog(revno, commitdate, author, msg, addedfiles, changedfiles, deletedfiles) \
                            values(?, ?, ?, ?,?, ?, ?)",
                            (revlog.revno, revlog.date, revlog.author, revlog.message, addedfiles, changedfiles, deletedfiles))
                for filename, changetype, linesadded, linesdeleted in revlog.getDiffLineCount(bUpdLineCount):                    
                    cur.execute("INSERT into SVNLogDetail(revno, changedpath, changetype, linesadded, linesdeleted, lc_updated) \
                                values(?, ?, ?, ?,?,?)", (revlog.revno, filename, changetype, linesadded, linesdeleted, lc_updated))
                    #print "%d : %s : %s : %d : %d " % (revlog.revno, filename, changetype, linesadded, linesdeleted)
                #commit after every change
                print "Number revisions converted : %d (Rev no : %d)" % (revcount, revlog.revno)                        
            cur.close()

    def UpdateLineCountData(self):
        self.initdb()
        try:        
            self.__updateLineCountData()
        except Exception, expinst:            
            logging.error("Error %s" % expinst)
            print "Error %s" % expinst            
        self.closedb()
        
    def __updateLineCountData(self):
        '''Update the line count data in SVNLogDetail where lc_update flag is 'N'.
        This function is to be used with incremental update of only 'line count' data.
        '''
        #first create temporary table from SVNLogDetail where only the lc_updated status is 'N'
        updcur = self.dbcon.cursor()
        cur = self.dbcon.cursor()
        cur.execute("CREATE TEMP TABLE IF NOT EXISTS LCUpdateStatus \
                    as select revno, changedpath, changetype from SVNLogDetail where lc_updated='N'")
        cur.execute("select revno, changedpath, changetype from LCUpdateStatus")
        
        for revno, changedpath, changetype in cur:
            linesadded, linesdeleted = self.svnclient.getDiffLineCountForPath(revno, changedpath, changetype)
##            updcur.execute("Update SVNLogDetail Set linesadded=%d, linesdeleted=%d, lc_updated='Y' \
##                    where revno=%d and changedpath='%s'")
##        
        updcur.close()           
        cur.close()
        self.dbcon.commit()
        
    def CreateTables(self):
        cur = self.dbcon.cursor()
        cur.execute("create table if not exists SVNLog(revno integer, commitdate timestamp, author text, msg text, \
                            addedfiles integer, changedfiles integer, deletedfiles integer)")
        cur.execute("create table if not exists SVNLogDetail(revno integer, changedpath text, changetype text,\
                    linesadded integer, linesdeleted integer, lc_updated char)")
        #lc_updated - Y means line count data is updated.
        #lc_updated - N means line count data is not updated. This flag can be used to update
        #line count data later        
        cur.execute("CREATE  INDEX if not exists svnlogrevnoidx ON SVNLog (revno ASC)")
        cur.execute("CREATE  INDEX if not exists svnlogdtlrevnoidx ON SVNLogDetail (revno ASC)")
        self.dbcon.commit()
        
        #Table structure is changed slightly. I have added a new column in SVNLogDetail table.
        #Use the following sql to alter the old tables
        #ALTER TABLE SVNLogDetail ADD COLUMN lc_updated char
        #update SVNLogDetail set lc_updated ='Y' ## Use 'Y' or 'N' as appropriate.

def RunMain():
    if( len(sys.argv) < 3):
        print "Usage : svnlog2sqlite.py <svnrepo url> <sqlitedbpath>"
    else:
        svnrepopath = sys.argv[1]
        sqlitedbpath = sys.argv[2]        
        try:
            conv = SVNLog2Sqlite(svnrepopath, sqlitedbpath)
            conv.convert()
        except:
            del conv
            raise
        
if( __name__ == "__main__"):
    RunMain()
    
    
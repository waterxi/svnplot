'''
svnlogiter.py
Copyright (C) 2009 Nitin Bhide (nitinbhide@gmail.com)

This module is part of SVNPlot (http://code.google.com/p/svnplot) and is released under
the New BSD License: http://www.opensource.org/licenses/bsd-license.php
--------------------------------------------------------------------------------------

This file implements the iterators to iterate over the subversion log.
This is just a convinience interface over the pysvn module.

It is intended to be used in  python script to convert the Subversion log into
an sqlite database.

To use copy the file in Python 'site-packages' directory Setup is not available
yet.
'''

import pysvn
import datetime, time
import os, re, string
import StringIO
import urllib
import logging
import getpass
import traceback
import types
import tempfile

def covert2datetime(seconds):
    gmt = time.gmtime(seconds)
    return(datetime.datetime(gmt.tm_year, gmt.tm_mon, gmt.tm_mday, gmt.tm_hour, gmt.tm_min, gmt.tm_sec))

def getDiffLineCountDict(diff_log):
    diffio = StringIO.StringIO(diff_log)
    addlnCount=0
    dellnCount=0
    curfile=None
    diffCountDict = dict()
    newfilediffstart = 'Index: '
    newfilepropdiffstart = 'Property changes on: '
    for diffline in diffio:
        #remove the newline characters near the end of line
        diffline = diffline.rstrip()
        if(diffline.find(newfilediffstart)==0):
            #diff for new file has started update the old filename.
            if(curfile != None):
                diffCountDict[curfile] = (addlnCount, dellnCount)
            #reset the linecounts and current filename
            addlnCount = 0
            dellnCount = 0
            #Index line entry doesnot have '/' as start of file path. Hence add the '/'
            #so that path entries in revision log list match with the names in the 'diff count' dictionary
            curfile = '/'+diffline[len(newfilediffstart):]
        elif(diffline.find(newfilepropdiffstart)==0):
            #property modification diff has started. Ignore it.
            if(curfile != None):
                diffCountDict[curfile] = (addlnCount, dellnCount)
            curfile = None
        elif(diffline.find('---')==0 or diffline.find('+++')==0 or diffline.find('@@')==0 or diffline.find('===')==0):                
            continue
        elif(diffline.find('-')==0):
            dellnCount = dellnCount+1                
        elif(diffline.find('+')==0):
             addlnCount = addlnCount+1
    
    #update last file stat in the dictionary.
    if( curfile != None):
        diffCountDict[curfile] = (addlnCount, dellnCount)
    return(diffCountDict)
    
class SVNLogClient:
    def __init__(self, svnrepourl):
        self.svnrepourl = svnrepourl
        self.svnclient = pysvn.Client()
        self.tmppath = None
        self._updateTempPath()
        self.maxTryCount = 3
        self.svnclient.callback_get_login = self.get_login
        self.svnclient.callback_ssl_server_trust_prompt = self.ssl_server_trust_prompt
        self.svnclient.callback_ssl_client_cert_password_prompt = self.ssl_client_cert_password_prompt
        
    
    def get_login(self, realm, username, may_save):
        logging.debug("This is a svnclient.callback_get_login event. ")
        user = raw_input("username for %s:" % realm)
        #save = True
        password = getpass.getpass()
        if(user==''): 
            retcode = False
        else:
            retcode = True
        return retcode, user, password, may_save

    def ssl_server_trust_prompt( self, trust_dict ):
        retcode=True
        accepted_failures = 1
        save=1
        print "trusting: "
        print trust_dict
        return retcode, accepted_failures, save
        
    def ssl_client_cert_password_prompt(self, realm, may_save):
        """callback_ssl_client_cert_password_prompt is called each time subversion needs a password in the realm to use a client certificate and has no cached credentials. """
        logging.debug("callback_ssl_client_cert_password_prompt called to gain password for subversion in realm %s ." %(realm))
        password = getpass.getpass()
        return retcode, password, may_save    
    
    def _updateTempPath(self):
        #Get temp directory
        tempdir = tempfile.gettempdir()
        self.tmppath = os.path.join(tempdir, "svnplot")
        
    def getHeadRevNo(self):
        revno = 0
        url = self.getUrl('')
        rooturl = self.svnclient.root_url_from_path(url)
        headrev = self._getHeadRev(rooturl)
        
        if( headrev != None):
            revno = headrev.revision.number
        else:
            print "Unable to find head revision for the repository"
            print "Check the firewall settings, network connection and repository path"
            
        return(revno)

    def _getHeadRev(self, rooturl):
        headrevlog = None
        headrev = pysvn.Revision( pysvn.opt_revision_kind.head )                    
        
        for trycount in range(0, self.maxTryCount):
            try:
                logging.info("Trying (%d) to get head revision" % trycount)
                revlog = self.svnclient.log( rooturl,
                     revision_start=headrev, revision_end=headrev, discover_changed_paths=False)
                #got the revision log. Now break out the multi-try for loop
                if( revlog != None and len(revlog) > 0):
                    revno = revlog[0].revision.number
                    logging.info("Found head revision %d" % revno)
                    headrevlog = revlog[0]
                    break                
            except Exception, expinst:
                logging.error("Error %s" % expinst)
                traceback.print_exc()
                continue
            
        return(headrevlog)
    
    def findStartEndRev(self):
        #Find svn-root for the url
        url = self.getUrl('')
        rooturl = self.svnclient.root_url_from_path(url)
        headrev = self._getHeadRev(rooturl)
        firstrev = self.getLog(1, url=rooturl, detailedLog=False)
        #headrev and first revision of the repository is found
        #actual start end revision numbers for given URL will be between these two numbers
        #Since svn log doesnot have a direct way of determining the start and end revisions
        #for a given url, I am using headrevision and first revision time to get those
        starttime = firstrev.date
        revstart = pysvn.Revision(pysvn.opt_revision_kind.date, starttime)
        startrev = self.svnclient.log( url,
                     revision_start=revstart, revision_end=headrev.revision, limit = 1, discover_changed_paths=False)
        
        startrevno = 0
        endrevno = 0
        if( startrev != None and len(startrev[0]) > 0):
            startrevno = startrev[0].revision.number
            endrevno   = headrev.revision.number
            
        return(startrevno, endrevno)        
        
    def getLog(self, revno, url=None, detailedLog=False):
        log=None
        if( url == None):
            url = self.getUrl('')
        rev = pysvn.Revision(pysvn.opt_revision_kind.number, revno)
                
        for trycount in range(0, self.maxTryCount):
            try:
                logging.info("Trying (%d) to get revision log" % trycount)
                revlog = self.svnclient.log( url,
                     revision_start=rev, revision_end=rev, discover_changed_paths=detailedLog)
                log = revlog[0]
                break
            except Exception, expinst:
                logging.error("Error %s" % expinst)
                traceback.print_exc()
                continue
        return(log)

    def getLogs(self, startrevno, endrevno, cachesize=1, detailedLog=False):
        revlog =None
        startrev = pysvn.Revision(pysvn.opt_revision_kind.number, startrevno)
        endrev = pysvn.Revision(pysvn.opt_revision_kind.number, endrevno)
        url = self.getUrl('')
                
        for trycount in range(0, self.maxTryCount):
            try:
                logging.info("Trying (%d) to get revision logs [%d:%d]" % (trycount,startrevno, endrevno))
                revlog = self.svnclient.log( url,
                     revision_start=startrev, revision_end=endrev, limit=cachesize,
                                             discover_changed_paths=detailedLog)                
                break
            except Exception, expinst:
                logging.error("Error %s" % expinst)
                continue        
        return(revlog)
    
    def getRevDiff(self, revno):
        rev1 = pysvn.Revision(pysvn.opt_revision_kind.number, revno-1)
        rev2 = pysvn.Revision(pysvn.opt_revision_kind.number, revno)
        url = self.getUrl('')
        diff_log = None
        for trycount in range(0, self.maxTryCount):
            try:
                logging.info("Trying (%d) to get revision diffs" % trycount)
                diff_log = self.svnclient.diff(self.tmppath, url, revision1=rev1, revision2=rev2,
                                recurse=True,ignore_ancestry=True,ignore_content_type=False,
                                       diff_deleted=True)
                break
            except Exception, expinst:                
                logging.error("Error %s" % expinst)
                continue
        return diff_log

    def getRevFileDiff(self, path, revno):
        rev1 = pysvn.Revision(pysvn.opt_revision_kind.number, revno-1)
        rev2 = pysvn.Revision(pysvn.opt_revision_kind.number, revno)
        url = self.getUrl(path)
        diff_log = None
        for trycount in range(0, self.maxTryCount):
            try:
                logging.info("Trying (%d) to get filelevel revision diffs" % trycount)
                diff_log = self.svnclient.diff(self.tmppath, url, revision1=rev1, revision2=rev2,
                            recurse=True, ignore_ancestry=False,ignore_content_type=False,
                                       diff_deleted=True)
                break
            except Exception, expinst:
                logging.error("Error %s" % expinst)
                continue
            
        return(diff_log)
    
    def getInfo(self, path, revno):
        '''Gets the information about the given path ONLY from the repository.
        Hence recurse flag is set to False.
        '''
        rev = pysvn.Revision(pysvn.opt_revision_kind.number, revno)
        url = self.getUrl(path)
        entry_list = None
        for trycount in range(0, self.maxTryCount):
            try:
                logging.debug("Trying (%d) to get file information" % trycount)
                entry_list = self.svnclient.info2( url,revision=rev,recurse=False)
                break
            except Exception, expinst:
                logging.error("Error %s" % expinst)
                continue
        return(entry_list)
    
    def getDiffLineCountForPath(self, revno, filepath, changetype):
        added = 0
        deleted = 0
        #print "getting diff count for %d:%s" % (revno, filepath)
        if( changetype != 'A' and changetype != 'D'):
            #file or directory is modified
            diff_log = self.getRevFileDiff(filepath, revno)
            diffDict = getDiffLineCountDict(diff_log)
            #The dictionary may not have the filepath key if only properties are modfiied.
            if(diffDict.has_key(filepath) == True):
                added, deleted = diffDict[filepath]
        elif( self.isDirectory(revno, filepath, changetype) == False):
            #path is added or deleted. First check if the path is a directory. If path is not a directory
            # then process further.
            if( changetype == 'A'):
                added = self.getLineCount(filepath, revno)
            elif( changetype == 'D'):
                deleted = self.getLineCount(filepath, revno-1)
            
        return(added, deleted)

    def isBinaryFile(self, filepath, revno):
        '''
        detect if file is a binary file using same heuristic as subversion. If the file
        has no svn:mime-type  property, or has a mime-type that is textual (e.g. text/*),
        Subversion assumes it is text. Otherwise it is treated as binary file.
        '''
        rev = pysvn.Revision(pysvn.opt_revision_kind.number, revno)
        url = self.getUrl(filepath)
        binary = None
        for trycount in range(0, self.maxTryCount):
            try:
                (revision, propdict) = self.svnclient.revproplist(url, revision=rev)
                binary = False #if explicit mime-type is not found always treat the file as 'text'                
                if( 'svn:mime-type' in propdict):
                    fmimetype = propdict['svn:mime-type']
                    if( fmimetype.find('text') < 0):
                       #mime type is not a 'text' mime type.
                       binary = True
                break
            except Exception, expinst:
                logging.error("Error %s" % expinst)
                continue
        
        return(binary)
    
    def isDirectory(self, revno, changepath, changetype):
        #if the file/dir is deleted in the current revision. Then the status needs to be checked for
        # one revision before that        
        if( changetype == 'D'):            
            revno = revno-1
        entry = self.getInfo(changepath, revno)
        filename, info_dict = entry[0]

        isDir = False            
        if( info_dict.kind == pysvn.node_kind.dir):
            isDir = True
        return(isDir)
        
    def _getLineCount(self, filepath, revno):
        linecount = 0
        for trycount in range(0, self.maxTryCount):
            try:
                logging.info("Trying (%d) to get linecount for %s" % (trycount, filepath))
                rev = pysvn.Revision(pysvn.opt_revision_kind.number, revno)
                url = self.getUrl(path)
                contents = self.svnclient.cat(url, revision = rev)
                matches = re.findall("$", contents, re.M )
                if( matches != None):
                    linecount = len(matches)
                logging.debug("%s linecount : %d" % (filepath, linecount))
                break
            except Exception, expinst:
                logging.error("Error %s" % expinst)
                continue
        return(linecount)
    
    def getLineCount(self, filepath, revno):
        linecount = 0
        if( self.isBinaryFile(filepath, revno) == False):
            linecount = self._getLineCount(filepath, revno)
        
        return(linecount)

    def getUrl(self, path):
        url = self.svnrepourl + urllib.pathname2url(path)
        return(url)
        
    def __iter__(self):
        return(SVNRevLogIter(self, 1, self.getHeadRevNo()))

class SVNRevLogIter:
    def __init__(self, logclient, startRevNo, endRevNo, cachesize=50):
        self.logclient = logclient
        self.startrev = startRevNo
        self.endrev = endRevNo
        self.revlogcache = None
        self.cachesize = cachesize
        
    def __iter__(self):
        return(self.next())

    def next(self):
        if( self.endrev == 0):
            self.endrev = self.logclient.getHeadRevNo()
        if( self.startrev == 0):
            self.startrev = self.endrev
        
        while (self.startrev < self.endrev):
            logging.info("updating logs %d to %d" % (self.startrev, self.endrev))
            self.revlogcache = self.logclient.getLogs(self.startrev, self.endrev,
                                                          cachesize=self.cachesize, detailedLog=True)
            if( self.revlogcache == None or len(self.revlogcache) == 0):
                raise StopIteration
            
            self.startrev = self.revlogcache[-1].revision.number+1
            for revlog in self.revlogcache:
                #since reach revision log entry is a dictionary. If the dictionary is empty
                #then log is not available or its end of log entries
                if( len(revlog) == 0):
                    raise StopIteration
                svnrevlog = SVNRevLog(self.logclient, revlog)
                yield svnrevlog
                                        
class SVNRevLog:
    def __init__(self, logclient, revnolog):
        self.logclient = logclient
        if( isinstance(revnolog, pysvn.PysvnLog) == False):
            self.revlog = self.logclient.getLog(revnolog, detailedLog=True)
        else:
            self.revlog = revnolog
        assert(self.revlog == None or isinstance(revnolog, pysvn.PysvnLog)==True)

    def isvalid(self):
        '''
        if the revision log is a valid log. Currently the log is invalid if the commit 'date' is not there.        
        '''
        valid = True
        if( self.__getattr__('date') == None):
            valid = False
        return(valid)
        
    def changedFileCount(self, bChkIfDir):
        '''includes directory and files. Initially I wanted to only add the changed file paths.
        however it is not possible to detect if the changed path is file or directory from the
        svn log output
        bChkIfDir -- If this flag is false, then treat all changed paths as files.
           since isDirectory function calls the svn client 'info' command, treating all changed
           paths as files will avoid calls to isDirectory function and speed up changed file count
           computations
        '''
        filesadded = 0
        fileschanged = 0
        filesdeleted = 0
        logging.debug("Changed path count : %d" % len(self.revlog.changed_paths))
        
        for change in self.revlog.changed_paths:
            isdir = False
            if( bChkIfDir == True):
                isdir = self.isDirectory(change)
            change['isdir'] = isdir
            action = change['action']
            if( isdir == False):
                if( action == 'M'):
                    fileschanged = fileschanged +1
                elif(action == 'A'):
                    filesadded = filesadded+1
                elif(action == 'D'):
                    filesdeleted = filesdeleted+1
        return(filesadded, fileschanged, filesdeleted)
        
    def isDirectory(self, change):
        path = change['path']
        action = change['action']
        isDir = False

        #see if directory check is alredy done on this path. If not, then check with the repository        
        if( 'isdir' not in change):
            revno = self.getRevNo()
            isDir = self.logclient.isDirectory(revno, path, action)            
        else:
            isDir = change['isdir']
            
        return(isDir)
        
    def getDiffLineCount(self, bUpdLineCount=True):
        """
        Returns a list of tuples containing filename, lines added and lines modified
        In case of binary files, lines added and deleted are returned as zero.
        In case of directory also lines added and deleted are returned as zero
        """                        
        diffCountDict = dict()
        if( bUpdLineCount == True):
            diffCountDict = self._updateDiffCount()
            
        diffCountList = []
        for change in self.revlog.changed_paths:
            linesadded = 0
            linesdeleted = 0
            filename = change['path']
            if( diffCountDict.has_key(filename)):
                linesadded, linesdeleted = diffCountDict[filename]
                                
            diffCountList.append((filename, change['action'],linesadded, linesdeleted))
            #print "%d : %s : %s : %d : %d " % (self.revno, filename, change['action'], linesadded, linesdeleted)        
        return(diffCountList)
        
    def getDiffLineCountForPath(self, change):
        added = 0
        deleted = 0
        revno = self.getRevNo()
        filename = change['path']
        changetype = change['action']
        if( changetype != 'A' and changetype != 'D'):
            #file or directory is modified
            diff_log = self.logclient.getRevFileDiff(filename, revno)
            diffDict = getDiffLineCountDict(diff_log)
            #The dictionary may not have the filename key if only properties are modfiied.
            if(diffDict.has_key(filename) == True):
                added, deleted = diffDict[filename]
        elif( self.isDirectory(change) == False):
            #path is added or deleted. First check if the path is a directory. If path is not a directory
            # then process further.
            if( changetype == 'A'):
                added = self.logclient.getLineCount(filename, revno)
            elif( changetype == 'D'):
                deleted = self.logclient.getLineCount(filename, revno-1)
            
        return(filename, changetype, added, deleted)

    def getRevNo(self):
        return(self.revlog.revision.number)
    
    def __getattr__(self, name):
        if(name == 'author'):
            author = ''
            #in case the author information is not available, then revlog object doesnot
            # contain 'author' attribute. This case needs to be handled. I am returning
            # empty string as author name.
            try:
                author =self.revlog.author
            except:
                pass
            return(author)
        elif(name == 'message'):
            msg = None
                
            try:
                msg = self.revlog.message
                if type(msg) == types.StringType: 
                    msg = unicode(msg, 'utf-8')

            except:
                msg = u''
            return(msg)
        elif(name == 'date'):
            try:
                dt = covert2datetime(self.revlog.date)
            except:
                dt = None
            return(dt)
        elif(name == 'revno'):
            return(self.revlog.revision.number)
        elif(name == 'changedpathcount'):
            filesadded, fileschanged, filesdeleted = self.changedFileCount(True)
            return(filesadded+fileschanged+filesdeleted)
        return(None)
    
    def _updateDiffCount(self):
        revno = self.getRevNo()
        revdiff_log = self.logclient.getRevDiff(revno)
        return(getDiffLineCountDict(revdiff_log))
                 